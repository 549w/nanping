"""缓存模块测试。

覆盖 cache.py 通用 TTL 缓存和 plugin_cache.py 插件缓存层。
"""

import asyncio
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.app.cache import TTLCache
from backend.app.plugin_cache import (
    clear_all_caches,
    get_all_stats,
)


# ============================================================
# TTLCache 单元测试
# ============================================================


class TestTTLCache:
    """通用 TTL 缓存测试。"""

    @pytest.mark.asyncio
    async def test_basic_set_get(self):
        """基本 set/get 应工作。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        """获取不存在的键应返回 None。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """过期条目应返回 None。"""
        cache = TTLCache(maxsize=10, default_ttl=0.1)  # 100ms TTL
        await cache.set("key1", "value1")

        # 立即获取应成功
        result = await cache.get("key1")
        assert result == "value1"

        # 等待过期
        await asyncio.sleep(0.15)

        # 应返回 None
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        """自定义 TTL 应覆盖默认值。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        await cache.set("key1", "value1", ttl=0.1)

        await asyncio.sleep(0.15)
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_maxsize_eviction(self):
        """超出容量应 LRU 淘汰。"""
        cache = TTLCache(maxsize=3, default_ttl=60)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        await cache.set("key4", "value4")  # 应淘汰 key1

        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"

    @pytest.mark.asyncio
    async def test_lru_refresh_on_get(self):
        """get 应刷新访问时间，避免淘汰。"""
        cache = TTLCache(maxsize=3, default_ttl=60)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # 访问 key1，刷新其 LRU 位置
        await cache.get("key1")

        # 新增 key4，应淘汰 key2（最久未访问）
        await cache.set("key4", "value4")

        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") is None
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"

    @pytest.mark.asyncio
    async def test_update_existing(self):
        """更新已有键应刷新值。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        await cache.set("key1", "value1")
        await cache.set("key1", "value2")
        result = await cache.get("key1")
        assert result == "value2"

    @pytest.mark.asyncio
    async def test_delete(self):
        """删除键应工作。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        await cache.set("key1", "value1")

        deleted = await cache.delete("key1")
        assert deleted is True
        assert await cache.get("key1") is None

        # 删除不存在的键
        deleted = await cache.delete("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_clear(self):
        """清空应工作。"""
        cache = TTLCache(maxsize=10, default_ttl=60)
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        count = await cache.clear()
        assert count == 2
        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """清理过期条目应工作。"""
        cache = TTLCache(maxsize=10, default_ttl=0.1)
        await cache.set("key1", "value1")
        await cache.set("key2", "value2", ttl=60)  # 长 TTL

        await asyncio.sleep(0.15)

        cleaned = await cache.cleanup_expired()
        assert cleaned == 1
        assert len(cache) == 1
        assert await cache.get("key2") == "value2"

    @pytest.mark.asyncio
    async def test_stats(self):
        """统计信息应正确。"""
        cache = TTLCache(maxsize=10, default_ttl=60)

        # 初始统计
        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

        # 写入
        await cache.set("key1", "value1")

        # 命中
        await cache.get("key1")
        await cache.get("key1")

        # 未命中
        await cache.get("nonexistent")

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3)
        assert stats["size"] == 1
        assert stats["maxsize"] == 10

    def test_len(self):
        """__len__ 应返回条目数。"""
        # 同步测试
        cache = TTLCache(maxsize=10, default_ttl=60)
        assert len(cache) == 0


# ============================================================
# 插件缓存集成测试
# ============================================================


class TestPluginCache:
    """插件缓存集成测试。"""

    @pytest_asyncio.fixture(autouse=True)
    async def clear_cache(self):
        """每个测试前清空缓存。"""
        await clear_all_caches()
        yield
        await clear_all_caches()

    @pytest.mark.asyncio
    async def test_cache_hit_on_same_request(
        self, client: AsyncClient, test_course, test_review
    ):
        """相同插件请求应命中缓存。"""
        # 第一次请求
        response1 = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "test",
                "gender": "men.png",
            },
        )
        assert response1.status_code == 200

        # 检查缓存统计
        stats1 = get_all_stats()

        # 第二次相同请求
        response2 = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "test",
                "gender": "men.png",
            },
        )
        assert response2.status_code == 200

        # 第二次应有缓存命中
        stats2 = get_all_stats()

        # 至少有一个缓存的命中数增加了
        total_hits_before = sum(s["hits"] for s in stats1.values())
        total_hits_after = sum(s["hits"] for s in stats2.values())
        assert total_hits_after > total_hits_before

    @pytest.mark.asyncio
    async def test_different_queries_no_cache_hit(
        self, client: AsyncClient, test_course, test_course2
    ):
        """不同查询不应命中缓存。"""
        # 第一次请求（查询 test_course）
        response1 = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "test",
                "gender": "men.png",
            },
        )
        assert response1.status_code == 200

        stats1 = get_all_stats()

        # 第二次请求（查询 test_course2）
        response2 = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00020", "teacher": "李四", "name": "另一门课"}
                ],
                "username": "test",
                "gender": "men.png",
            },
        )
        assert response2.status_code == 200

        stats2 = get_all_stats()

        # 缓存大小应增加（新键被添加）
        total_size_before = sum(s["size"] for s in stats1.values())
        total_size_after = sum(s["size"] for s in stats2.values())
        assert total_size_after > total_size_before

    @pytest.mark.asyncio
    async def test_clear_all_caches(self, client: AsyncClient, test_course):
        """清空所有缓存应工作。"""
        # 发送请求填充缓存
        await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "test",
                "gender": "men.png",
            },
        )

        # 检查缓存非空
        stats = get_all_stats()
        total_size = sum(s["size"] for s in stats.values())
        assert total_size > 0

        # 清空
        cleared = await clear_all_caches()
        assert cleared > 0

        # 验证已清空
        stats = get_all_stats()
        total_size = sum(s["size"] for s in stats.values())
        assert total_size == 0
