"""通用 TTL 缓存。

轻量级内存缓存实现，支持：
- 基于时间的过期（TTL）
- 容量上限（LRU 淘汰）
- 异步安全（asyncio.Lock）
- 命中统计

设计原则：
- 无外部依赖（不引入 cachetools/redis 等）
- 简单可靠，适合单进程部署
- 提供统计信息便于监控
"""

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nanping.cache")


@dataclass
class CacheEntry:
    """缓存条目。"""

    value: Any
    expires_at: float  # time.monotonic() 绝对时间


class TTLCache:
    """带 TTL 和容量上限的异步缓存。

    使用 OrderedDict 实现 LRU 淘汰：最近访问的条目移到末尾，
    超出容量时淘汰最久未访问的条目。

    线程安全：使用 asyncio.Lock 保护并发访问。

    Example:
        >>> cache = TTLCache(maxsize=100, default_ttl=60)
        >>> await cache.set("key1", "value1")
        >>> await cache.get("key1")
        'value1'
    """

    def __init__(self, maxsize: int = 1000, default_ttl: float = 300.0):
        """初始化缓存。

        Args:
            maxsize: 最大缓存条目数，超出后 LRU 淘汰
            default_ttl: 默认过期时间（秒）
        """
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        self._default_ttl = default_ttl

        # 统计
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Any | None:
        """获取缓存值。

        命中时刷新访问时间（LRU）。
        过期或不存在返回 None。

        Args:
            key: 缓存键

        Returns:
            缓存值，或 None
        """
        async with self._lock:
            if key not in self._store:
                self._misses += 1
                return None

            entry = self._store[key]
            now = time.monotonic()

            # 检查过期
            if now >= entry.expires_at:
                del self._store[key]
                self._misses += 1
                return None

            # 命中：移到末尾（LRU）
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """设置缓存。

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 使用默认值
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + effective_ttl

        async with self._lock:
            # 更新或新增
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = CacheEntry(value=value, expires_at=expires_at)
            else:
                self._store[key] = CacheEntry(value=value, expires_at=expires_at)
                # 容量淘汰
                while len(self._store) > self._maxsize:
                    evicted_key, _ = self._store.popitem(last=False)
                    logger.debug("缓存淘汰: key=%s", evicted_key[:20])

    async def delete(self, key: str) -> bool:
        """删除缓存。

        Args:
            key: 缓存键

        Returns:
            True 表示成功删除，False 表示键不存在
        """
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear(self) -> int:
        """清空所有缓存。

        Returns:
            清理的条目数
        """
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            self._hits = 0
            self._misses = 0
            return count

    async def cleanup_expired(self) -> int:
        """清理所有过期条目。

        Returns:
            清理的条目数
        """
        now = time.monotonic()
        expired_keys = []

        async with self._lock:
            for key, entry in self._store.items():
                if now >= entry.expires_at:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._store[key]

        if expired_keys:
            logger.debug("清理过期缓存: %d 条", len(expired_keys))

        return len(expired_keys)

    def stats(self) -> dict:
        """返回缓存统计信息。

        Returns:
            包含 size, maxsize, hits, misses, hit_rate 的字典
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "size": len(self._store),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }

    def __len__(self) -> int:
        """返回当前缓存条目数。"""
        return len(self._store)
