"""slowapi 限流器。

独立模块，避免 main.py ↔ routers 循环导入。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
