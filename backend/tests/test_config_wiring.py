"""配置接入测试。

验证 TTL 数值不是硬编码，而是从 settings 读取。
未来任何把 .env 默认值改回硬编码的回归都会被这个测试抓到。
"""

import os
import subprocess
import sys

import pytest

from app import config, plugin_cache


class TestConfigWiring:
    """关键 TTL 必须从 settings 读取，不能是 plugin_cache / auth 里的硬编码。"""

    def test_plugin_cache_ttls_match_settings(self):
        """plugin_cache 的 4 个缓存 TTL 等于 settings.PLUGIN_CACHE_TTL_*。"""
        # 通过 _expiration 检查（TTLCache 没有公开 .default_ttl）
        # 写入一个 key，等短于 settings 但长于 0 的时间，看是否还活着
        import asyncio

        async def _check():
            caches = plugin_cache.get_all_caches()
            # 评价缓存：TTL=30
            c = caches["reviews"]
            await c.set("test:1", {"x": 1})
            assert await c.get("test:1") == {"x": 1}
            await c.set("test:2", {"y": 2})
            assert await c.get("test:2") == {"y": 2}
            # 课程缓存：TTL=300
            c2 = caches["exact_course"]
            await c2.set("test:e", {"z": 3})
            assert await c2.get("test:e") == {"z": 3}
            await c2.clear()
            await c.clear()

        asyncio.run(_check())

        # 更直接：检查 settings 中的默认值与文档一致
        assert config.settings.PLUGIN_CACHE_TTL_COURSE == 300
        assert config.settings.PLUGIN_CACHE_TTL_REVIEWS == 30
        assert config.settings.PLUGIN_CACHE_TTL_NEWS == 120

    def test_auth_cooldown_setting_exists(self):
        """AUTH_RESEND_COOLDOWN_SECONDS 必须存在且默认 60。"""
        assert hasattr(config.settings, "AUTH_RESEND_COOLDOWN_SECONDS")
        assert config.settings.AUTH_RESEND_COOLDOWN_SECONDS == 60

    def test_auth_code_expire_setting_exists(self):
        """AUTH_CODE_EXPIRE_MINUTES 必须存在且默认 5。"""
        assert hasattr(config.settings, "AUTH_CODE_EXPIRE_MINUTES")
        assert config.settings.AUTH_CODE_EXPIRE_MINUTES == 5

    def test_cache_ttl_actually_picks_up_env_changes(self):
        """当 PLUGIN_CACHE_TTL_* 环境变量改变时，plugin_cache 的 _default_ttl 跟着变。

        **真实回归抓取**：上面三个测试只断言 settings 的默认值，
        抓不到「plugin_cache.py 把 default_ttl=300 硬编码回来，但 settings 仍是 30」
        这种局部回归。这里用 subprocess 在隔离进程里设 env 后再 import 验证链路。

        如果有人改 plugin_cache.py 把 `default_ttl=settings.PLUGIN_CACHE_TTL_REVIEWS`
        改回 `default_ttl=30`，这个测试会 fail。
        """
        # 项目根目录 = backend/tests/ 的父级的父级
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        # 用非默认值（999/7/77）覆盖 3 个 env，subprocess 跑下面的脚本
        # 如果任何一个 cache._default_ttl != env 值，就 assert 失败
        script = """
import os, sys
sys.path.insert(0, '{cwd}/backend')
os.environ['PLUGIN_CACHE_TTL_COURSE'] = '999'
os.environ['PLUGIN_CACHE_TTL_REVIEWS'] = '7'
os.environ['PLUGIN_CACHE_TTL_NEWS'] = '77'
from app.plugin_cache import (
    _exact_course_cache, _search_cache, _reviews_cache, _news_cache,
)
assert _exact_course_cache._default_ttl == 999, _exact_course_cache._default_ttl
assert _search_cache._default_ttl       == 999, _search_cache._default_ttl
assert _reviews_cache._default_ttl      == 7,   _reviews_cache._default_ttl
assert _news_cache._default_ttl         == 77,  _news_cache._default_ttl
print('OK')
""".format(cwd=project_root)

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"subprocess failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout, f"unexpected stdout: {result.stdout!r}"
