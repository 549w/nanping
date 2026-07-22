"""API 风控模块 — 异常爬取行为检测。

本模块提供基于匿名 session 的风控能力：
- 通过 Cookie 追踪同一浏览器的行为（跨 IP）
- 多维度风险评分（请求速率、课程遍历、顺序访问等）
- 分级响应（低风险放行、中风险警告、高风险封禁）

设计原则：
- 本文件为纯逻辑层，无 FastAPI 依赖，便于单元测试
- 中间件集成在 risk_middleware.py
"""

import asyncio
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("nanping.risk")


# ============================================================
# 数据结构
# ============================================================


class RiskLevel(str, Enum):
    """风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class RiskResult:
    """风险评分结果。"""

    score: float
    level: RiskLevel
    components: dict[str, float]
    reasons: list[str]


@dataclass
class SessionState:
    """单个匿名会话的状态。

    所有时间字段使用 time.monotonic()，避免系统时间调整影响。
    """

    session_id: str
    created_at: float
    last_seen: float

    # 行为追踪
    ip_addresses: set[str] = field(default_factory=set)
    is_authenticated: bool = False

    # 滚动窗口数据（最近 10 分钟）
    request_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    # course_id 访问记录：(course_id, timestamp) 元组，用于时间窗口清理
    course_id_history: deque[tuple[int, float]] = field(default_factory=lambda: deque(maxlen=1000))
    course_id_sequence: deque[int] = field(default_factory=lambda: deque(maxlen=50))  # 最近 50 个（有序）
    search_keywords: deque[tuple[str, float]] = field(default_factory=lambda: deque(maxlen=200))

    # 统计计数
    total_requests: int = 0
    plugin_request_count: int = 0

    # 封禁状态
    blocked_until: float | None = None


class SessionStore:
    """内存会话存储。

    线程安全（asyncio.Lock），支持 TTL 清理。
    """

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> SessionState:
        """获取或创建会话。"""
        async with self._lock:
            if session_id not in self._sessions:
                now = time.monotonic()
                self._sessions[session_id] = SessionState(
                    session_id=session_id,
                    created_at=now,
                    last_seen=now,
                )
            return self._sessions[session_id]

    async def cleanup(self, ttl_seconds: float) -> int:
        """清理过期会话，返回清理数量。"""
        now = time.monotonic()
        expired = []

        async with self._lock:
            for sid, session in self._sessions.items():
                if now - session.last_seen > ttl_seconds:
                    expired.append(sid)

            for sid in expired:
                del self._sessions[sid]

        if expired:
            logger.debug("清理 %d 个过期会话", len(expired))

        return len(expired)

    async def get_all(self) -> list[SessionState]:
        """获取所有会话（调试用）。"""
        async with self._lock:
            return list(self._sessions.values())


# ============================================================
# 行为追踪
# ============================================================


def generate_session_id() -> str:
    """生成新的 session ID。"""
    return uuid.uuid4().hex


def extract_course_id_from_path(path: str) -> int | None:
    """从 URL 路径提取 course_id。

    支持：
    - /courses/123 → 123
    - /review?course_id=456 → 需要另外处理 query param

    Args:
        path: URL 路径

    Returns:
        course_id 或 None
    """
    match = re.match(r"^/courses/(\d+)$", path)
    if match:
        return int(match.group(1))
    return None


def compute_intervals(timestamps: deque[float]) -> list[float]:
    """计算请求间隔序列。"""
    if len(timestamps) < 2:
        return []
    ts_list = list(timestamps)
    return [ts_list[i] - ts_list[i - 1] for i in range(1, len(ts_list))]


def compute_sequential_ratio(course_ids: deque[int] | list[int]) -> float:
    """计算 course_id 序列的连续递增比例。

    连续定义：相邻两个 course_id 差值 ≤ 3。

    Args:
        course_ids: 有序的 course_id 序列

    Returns:
        连续比例 (0.0 ~ 1.0)，样本不足返回 0.0
    """
    if len(course_ids) < 10:
        return 0.0

    ids_list = list(course_ids)
    consecutive = 0
    for i in range(1, len(ids_list)):
        if abs(ids_list[i] - ids_list[i - 1]) <= 3:
            consecutive += 1

    return consecutive / (len(ids_list) - 1)


def compute_interval_regularity(intervals: list[float]) -> bool:
    """检测请求间隔是否高度规律。

    规律定义：标准差 < 均值的 10%，且样本 > 20。

    Args:
        intervals: 请求间隔序列

    Returns:
        True 表示高度规律
    """
    if len(intervals) < 20:
        return False

    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return False

    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    std = variance ** 0.5

    return std < mean * 0.1


# ============================================================
# 风险评分
# ============================================================


def compute_risk_score(
    session: SessionState,
    now: float,
    *,
    rate_threshold: int = 100,
    course_threshold: int = 200,
    sequential_threshold: float = 0.8,
    auth_discount: float = 0.5,
) -> RiskResult:
    """计算当前会话的风险分数。

    Args:
        session: 会话状态
        now: 当前时间 (time.monotonic())
        rate_threshold: 1 分钟请求速率阈值
        course_threshold: 10 分钟独立课程数阈值
        sequential_threshold: 连续递增比例阈值
        auth_discount: 已登录用户折扣系数

    Returns:
        RiskResult
    """
    components: dict[str, float] = {}
    reasons: list[str] = []

    # 计算时间窗口
    window_1min = now - 60
    window_10min = now - 600

    # 过滤窗口内的时间戳
    recent_1min = [t for t in session.request_timestamps if t >= window_1min]

    # 1. 请求速率维度
    rate_1min = len(recent_1min)
    if rate_1min > rate_threshold:
        score = 30.0
        components["rate_1min"] = score
        reasons.append(f"rate={rate_1min}/min")

    # 2. 独立课程数维度（基于时间窗口内的 course_id_history）
    recent_course_ids = {
        cid for cid, ts in session.course_id_history if ts >= window_10min
    }
    unique_courses = len(recent_course_ids)
    if unique_courses > course_threshold:
        score = 50.0
        components["unique_courses"] = score
        reasons.append(f"courses={unique_courses}")

    # 3. 连续递增维度
    seq_ratio = compute_sequential_ratio(session.course_id_sequence)
    if seq_ratio > sequential_threshold:
        score = 30.0
        components["sequential"] = score
        reasons.append(f"seq={seq_ratio:.0%}")

    # 4. 间隔规律性维度
    intervals = compute_intervals(session.request_timestamps)
    if compute_interval_regularity(intervals):
        score = 20.0
        components["regular_interval"] = score
        reasons.append("regular")

    # 5. 多 IP 维度
    if len(session.ip_addresses) > 3:
        score = 15.0
        components["multi_ip"] = score
        reasons.append(f"ips={len(session.ip_addresses)}")

    # 计算总分（无衰减 - 时间窗口已提供遗忘机制）
    final_score = sum(components.values())

    # 认证折扣
    if session.is_authenticated:
        final_score *= auth_discount

    # 确定风险等级
    if final_score >= 70:
        level = RiskLevel.HIGH
    elif final_score >= 30:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    return RiskResult(
        score=final_score,
        level=level,
        components=components,
        reasons=reasons,
    )


# ============================================================
# 日志辅助
# ============================================================


def format_risk_log(
    session: SessionState,
    result: RiskResult,
    action: str,
    now: float | None = None,
) -> str:
    """格式化风控日志。

    Args:
        session: 会话状态
        result: 评分结果
        action: 动作 ("allow" / "warn" / "block")
        now: 当前时间，None 则使用 session.last_seen

    Returns:
        格式化日志字符串
    """
    parts = [
        f"session={session.session_id[:8]}",
        f"risk={result.level.value}",
        f"score={result.score:.0f}",
        f"action={action}",
    ]

    if result.reasons:
        parts.append(f"reasons={','.join(result.reasons)}")

    # 计算最近 10 分钟的独立课程数
    window_time = now if now is not None else session.last_seen
    window_10min = window_time - 600
    recent_courses = len({cid for cid, ts in session.course_id_history if ts >= window_10min})

    parts.extend([
        f"total={session.total_requests}",
        f"courses_10m={recent_courses}",
        f"ips={len(session.ip_addresses)}",
        f"auth={session.is_authenticated}",
    ])

    return " | ".join(parts)
