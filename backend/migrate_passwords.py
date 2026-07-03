#!/usr/bin/env python3
"""迁移现有用户密码从 bcrypt(plaintext) 到 bcrypt(SHA-256(plaintext))。

由于我们不知道原始明文密码，此脚本会尝试常见测试密码并迁移匹配的用户。
仅适用于测试/开发环境。生产环境需要强制用户重置密码。
"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.auth import verify_password, hash_password, normalize_password
from backend.app.database import async_session
from backend.app.models import User
from sqlalchemy import select

# 常见测试密码列表
COMMON_TEST_PASSWORDS = []


async def migrate_passwords():
    """迁移所有用户的密码。"""
    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        migrated_count = 0
        failed_count = 0

        print(f"找到 {len(users)} 个用户")
        print("=" * 60)

        for user in users:
            print(f"\n处理用户: {user.email}")

            # 尝试常见测试密码
            migrated = False
            for test_pwd in COMMON_TEST_PASSWORDS:
                if verify_password(test_pwd, user.password):
                    # 找到匹配的密码，进行迁移
                    print(f"  ✓ 匹配密码: {test_pwd}")
                    normalized = normalize_password(test_pwd)
                    user.password = hash_password(normalized)
                    await db.commit()
                    print(f"  ✓ 已迁移密码 (SHA-256 + bcrypt)")
                    migrated_count += 1
                    migrated = True
                    break

            if not migrated:
                print(f"  ✗ 未找到匹配的常见密码，跳过")
                failed_count += 1

        print("\n" + "=" * 60)
        print(f"迁移完成: {migrated_count} 个用户成功, {failed_count} 个用户失败")

        if failed_count > 0:
            print(f"\n注意: {failed_count} 个用户的密码未迁移。")
            print("这些用户需要手动重置密码或提供原始密码。")


if __name__ == "__main__":
    asyncio.run(migrate_passwords())
