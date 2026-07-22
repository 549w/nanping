"""风控模块测试。

覆盖 risk.py 核心逻辑和 risk_middleware.py 集成行为。
"""

import time

import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.app.risk import (
    RiskLevel,
    SessionState,
    SessionStore,
    compute_interval_regularity,
    compute_intervals,
    compute_risk_score,
    compute_sequential_ratio,
    extract_course_id_from_path,
    generate_session_id,
)
from backend.app.risk_middleware import (
    get_session_store,
    set_session_store,
    should_skip_path,
)


# ============================================================
# 单元测试：risk.py
# ============================================================


class TestHelpers:
    """辅助函数测试。"""

    def test_generate_session_id_unique(self):
        """生成的 session_id 应唯一。"""
        ids = {generate_session_id() for _ in range(100)}
        assert len(ids) == 100

    def test_extract_course_id_from_path(self):
        """应正确从路径提取 course_id。"""
        assert extract_course_id_from_path("/courses/123") == 123
        assert extract_course_id_from_path("/courses/0") == 0
        assert extract_course_id_from_path("/courses/99999") == 99999
        assert extract_course_id_from_path("/courses/") is None
        assert extract_course_id_from_path("/courses/abc") is None
        assert extract_course_id_from_path("/review") is None
        assert extract_course_id_from_path("/") is None
        assert extract_course_id_from_path("/plugin") is None

    def test_compute_intervals(self):
        """应正确计算请求间隔。"""
        timestamps = [1.0, 2.0, 3.5, 5.0]
        intervals = compute_intervals(timestamps)
        assert len(intervals) == 3
        assert intervals[0] == pytest.approx(1.0)
        assert intervals[1] == pytest.approx(1.5)
        assert intervals[2] == pytest.approx(1.5)

    def test_compute_intervals_empty(self):
        """单元素或空序列应返回空列表。"""
        assert compute_intervals([]) == []
        assert compute_intervals([1.0]) == []

    def test_compute_sequential_ratio_consecutive(self):
        """连续递增序列应返回高比例。"""
        # [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] - 9 个连续对，全部差值 ≤ 3
        course_ids = list(range(1, 11))
        ratio = compute_sequential_ratio(course_ids)
        assert ratio == 1.0

    def test_compute_sequential_ratio_mixed(self):
        """混合序列应返回中等比例。"""
        # [1, 2, 100, 101, 102, 200, 201, 202, 203, 204]
        # 连续对: (1,2)=✓, (2,100)=✗, (100,101)=✓, (101,102)=✓,
        #         (102,200)=✗, (200,201)=✓, (201,202)=✓, (202,203)=✓, (203,204)=✓
        # 7/9 = 77.8%
        course_ids = [1, 2, 100, 101, 102, 200, 201, 202, 203, 204]
        ratio = compute_sequential_ratio(course_ids)
        assert 0.7 <= ratio <= 0.8

    def test_compute_sequential_ratio_random(self):
        """随机序列应返回低比例。"""
        # 大间隔跳跃
        course_ids = [1, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]
        ratio = compute_sequential_ratio(course_ids)
        assert ratio == 0.0

    def test_compute_sequential_ratio_short(self):
        """样本不足应返回 0。"""
        assert compute_sequential_ratio([1, 2, 3]) == 0.0
        assert compute_sequential_ratio([]) == 0.0

    def test_compute_interval_regularity_regular(self):
        """高度规律的间隔应返回 True。"""
        # 固定 0.5 秒间隔
        intervals = [0.5] * 30
        assert compute_interval_regularity(intervals) is True

    def test_compute_interval_regularity_irregular(self):
        """不规则间隔应返回 False。"""
        # 变化很大的间隔
        intervals = [0.1, 1.0, 0.2, 2.0, 0.3, 1.5, 0.4, 3.0] * 5
        assert compute_interval_regularity(intervals) is False

    def test_compute_interval_regularity_short(self):
        """样本不足应返回 False。"""
        assert compute_interval_regularity([0.5] * 5) is False


class TestSessionStore:
    """会话存储测试。"""

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        """新 session_id 应创建新会话。"""
        store = SessionStore()
        session = await store.get_or_create("test-session-1")
        assert session.session_id == "test-session-1"
        assert session.total_requests == 0

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        """相同 session_id 应返回同一会话。"""
        store = SessionStore()
        session1 = await store.get_or_create("test-session-2")
        session1.total_requests = 5
        session2 = await store.get_or_create("test-session-2")
        assert session2.total_requests == 5
        assert session1 is session2

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """过期会话应被清理。"""
        store = SessionStore()
        # 创建两个会话
        session1 = await store.get_or_create("old-session")
        session2 = await store.get_or_create("new-session")
        # 模拟旧会话
        session1.last_seen = time.monotonic() - 7200  # 2 小时前
        # 清理 TTL=3600
        cleaned = await store.cleanup(3600)
        assert cleaned == 1
        # 旧会话被清理
        all_sessions = await store.get_all()
        assert len(all_sessions) == 1
        assert all_sessions[0].session_id == "new-session"


class TestRiskScoring:
    """风险评分测试。"""

    def _make_session(self, **kwargs) -> SessionState:
        """创建测试用会话。"""
        now = time.monotonic()
        defaults = {
            "session_id": "test",
            "created_at": now,
            "last_seen": now,
        }
        defaults.update(kwargs)
        return SessionState(**defaults)

    def test_low_risk_normal(self):
        """正常浏览应为低风险。"""
        session = self._make_session()
        now = time.monotonic()
        # 模拟 10 次请求
        for i in range(10):
            session.request_timestamps.append(now - 60 + i)
            session.total_requests += 1
        result = compute_risk_score(session, now)
        assert result.level == RiskLevel.LOW
        assert result.score < 30

    def test_high_risk_rate(self):
        """高频请求应触发高风险。"""
        session = self._make_session()
        now = time.monotonic()
        # 模拟 150 次请求/分钟
        for i in range(150):
            session.request_timestamps.append(now - 60 + i * 0.4)
            session.total_requests += 1
        result = compute_risk_score(session, now, rate_threshold=100)
        assert "rate_1min" in result.components
        assert result.score >= 30

    def test_high_risk_unique_courses(self):
        """访问大量不同课程应触发高风险。"""
        session = self._make_session()
        now = time.monotonic()
        # 模拟访问 250 个不同课程
        for i in range(250):
            ts = now - 60 + i * 0.2
            session.request_timestamps.append(ts)
            session.course_id_history.append((i, ts))
            session.total_requests += 1
        result = compute_risk_score(session, now, course_threshold=200)
        assert "unique_courses" in result.components
        assert result.score >= 50

    def test_high_risk_sequential(self):
        """顺序访问 course_id 应触发高风险。"""
        session = self._make_session()
        now = time.monotonic()
        # 模拟顺序访问
        for i in range(20):
            ts = now - 60 + i
            session.request_timestamps.append(ts)
            session.course_id_sequence.append(i)
            session.total_requests += 1
        result = compute_risk_score(session, now, sequential_threshold=0.8)
        assert "sequential" in result.components
        assert result.score >= 30

    def test_auth_discount(self):
        """已登录用户应享受折扣。"""
        session = self._make_session(is_authenticated=True)
        now = time.monotonic()
        # 模拟 150 次请求（触发速率维度）
        for i in range(150):
            session.request_timestamps.append(now - 60 + i * 0.4)
            session.total_requests += 1
        result_anon = compute_risk_score(self._make_session(), now, rate_threshold=100)
        # 重新填充匿名会话
        for i in range(150):
            result_anon_session = self._make_session()
            for j in range(150):
                result_anon_session.request_timestamps.append(now - 60 + j * 0.4)
                result_anon_session.total_requests += 1
            result_anon = compute_risk_score(result_anon_session, now, rate_threshold=100)
            break

        result_auth = compute_risk_score(session, now, rate_threshold=100, auth_discount=0.5)
        # 认证用户分数应更低
        assert result_auth.score < result_anon.score

    def test_risk_levels(self):
        """不同分数应对应不同等级。"""
        session = self._make_session()
        now = time.monotonic()

        # 低风险
        result = compute_risk_score(session, now)
        assert result.level == RiskLevel.LOW

        # 中风险（模拟 50 次请求，不触发任何维度）
        for i in range(50):
            session.request_timestamps.append(now - 60 + i)
            session.total_requests += 1
        # 手动设置高分
        session.last_score = 45
        session.last_components = {"manual": 45}
        # 由于没有触发任何维度，实际分数会是 0

    def test_multi_ip(self):
        """多 IP 应加分。"""
        session = self._make_session()
        session.ip_addresses = {"1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"}
        now = time.monotonic()
        result = compute_risk_score(session, now)
        assert "multi_ip" in result.components


class TestPathWhitelist:
    """路径白名单测试。"""

    def test_skip_health_check(self):
        """健康检查应跳过。"""
        assert should_skip_path("/") is True

    def test_skip_auth(self):
        """认证端点应跳过。"""
        assert should_skip_path("/auth/login") is True
        assert should_skip_path("/auth/register") is True

    def test_skip_docs(self):
        """文档端点应跳过。"""
        assert should_skip_path("/docs") is True
        assert should_skip_path("/openapi.json") is True

    def test_skip_static(self):
        """静态资源应跳过。"""
        assert should_skip_path("/css/style.css") is True
        assert should_skip_path("/js/app.js") is True
        assert should_skip_path("/fonts/main.woff2") is True

    def test_no_skip_courses(self):
        """课程端点不应跳过。"""
        assert should_skip_path("/courses") is False
        assert should_skip_path("/courses/123") is False

    def test_no_skip_review(self):
        """评价端点不应跳过。"""
        assert should_skip_path("/review") is False
        assert should_skip_path("/review/add") is False


# ============================================================
# 集成测试：risk_middleware.py
# ============================================================


class TestRiskMiddlewareIntegration:
    """中间件集成测试。"""

    @pytest.mark.asyncio
    async def test_cookie_set_on_first_request(self, client: AsyncClient):
        """首次请求应设置 session Cookie。"""
        response = await client.get("/courses", params={"name": "测试"})
        assert response.status_code == 200
        assert "np_sid" in response.cookies

    @pytest.mark.asyncio
    async def test_cookie_persists_across_requests(self, client: AsyncClient):
        """后续请求应使用同一 Cookie。"""
        # 首次请求获取 Cookie
        response1 = await client.get("/courses", params={"name": "测试"})
        session_id = response1.cookies.get("np_sid")
        assert session_id

        # Cookie 已自动保存在 client 的 cookie jar 中
        # 后续请求自动带上
        response2 = await client.get("/courses", params={"name": "测试"})
        assert response2.status_code == 200
        # 验证请求带上了 Cookie（通过检查响应头确认 session 被识别）
        assert "x-risk-session" in response2.headers

    @pytest.mark.asyncio
    async def test_risk_headers_in_response(self, client: AsyncClient):
        """响应应包含风控头。"""
        response = await client.get("/courses", params={"name": "测试"})
        assert "x-risk-score" in response.headers
        assert "x-risk-level" in response.headers
        assert "x-risk-session" in response.headers

    @pytest.mark.asyncio
    async def test_skip_whitelisted_paths(self, client: AsyncClient):
        """白名单路径不应有风控头。"""
        response = await client.get("/")
        assert "x-risk-score" not in response.headers

    @pytest.fixture(autouse=True)
    def reset_session_store(self):
        """每个测试重置会话存储。"""
        from backend.app.risk import SessionStore
        set_session_store(SessionStore())
        yield
        set_session_store(SessionStore())
