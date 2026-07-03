"""认证端点测试。

覆盖 POST /auth/send-code、/auth/register、/auth/login 的正常与异常路径。
"""

import time

import pytest


class TestSendCode:
    """POST /auth/send-code 测试。"""

    @pytest.mark.asyncio
    async def test_send_code_success(self, client):
        """正常发送验证码应返回 200。"""
        response = await client.post(
            "/auth/send-code",
            json={"email": "newuser@nju.edu.cn"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "验证码已发送"

    @pytest.mark.asyncio
    async def test_send_code_cooldown(self, client):
        """60 秒内重复发送应返回 429。"""
        await client.post("/auth/send-code", json={"email": "cooldown@nju.edu.cn"})
        response = await client.post(
            "/auth/send-code",
            json={"email": "cooldown@nju.edu.cn"},
        )
        assert response.status_code == 429
        assert "60" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_send_code_invalid_email_domain(self, client):
        """非南大邮箱应返回 422。"""
        response = await client.post(
            "/auth/send-code",
            json={"email": "user@gmail.com"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_send_code_invalid_email_format(self, client):
        """非法邮箱格式应返回 422。"""
        response = await client.post(
            "/auth/send-code",
            json={"email": "not-an-email"},
        )
        assert response.status_code == 422


class TestRegister:
    """POST /auth/register 测试。"""

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        """完整注册流程：发验证码 → 注册 → 成功。"""
        await client.post("/auth/send-code", json={"email": "register@nju.edu.cn"})
        response = await client.post(
            "/auth/register",
            json={
                "email": "register@nju.edu.cn",
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 201
        assert response.json()["message"] == "注册成功"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client, test_user):
        """重复邮箱注册应返回 409。"""
        await client.post("/auth/send-code", json={"email": "test@nju.edu.cn"})
        response = await client.post(
            "/auth/register",
            json={
                "email": "test@nju.edu.cn",
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 409
        assert "已注册" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_wrong_code(self, client):
        """错误验证码应返回 400。"""
        await client.post("/auth/send-code", json={"email": "wrongcode@nju.edu.cn"})
        response = await client.post(
            "/auth/register",
            json={
                "email": "wrongcode@nju.edu.cn",
                "code": "000000",
                "password": "password123",
            },
        )
        assert response.status_code == 400
        assert "验证码" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_no_code_sent(self, client):
        """未发送验证码直接注册应返回 400。"""
        response = await client.post(
            "/auth/register",
            json={
                "email": "nosend@nju.edu.cn",
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_register_expired_code(self, client):
        """过期验证码应返回 400。"""
        from datetime import datetime, timezone, timedelta

        from backend.app.routers.auth import _verification_codes, CodeEntry

        # 手动注入一个已过期的验证码
        email = "expired@nju.edu.cn"
        _verification_codes[email] = CodeEntry(
            code="123456",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            last_sent_at=datetime.now(timezone.utc) - timedelta(minutes=6),
        )

        response = await client.post(
            "/auth/register",
            json={
                "email": email,
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 400
        assert "过期" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        """密码过短应返回 422。"""
        await client.post("/auth/send-code", json={"email": "shortpw@nju.edu.cn"})
        response = await client.post(
            "/auth/register",
            json={
                "email": "shortpw@nju.edu.cn",
                "code": "123456",
                "password": "12345",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client):
        """非法邮箱格式应返回 422。"""
        response = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_non_nju_email(self, client):
        """非南大邮箱域名应返回 422。"""
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@gmail.com",
                "code": "123456",
                "password": "password123",
            },
        )
        assert response.status_code == 422


class TestLogin:
    """POST /auth/login 测试。"""

    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        """正确凭据登录应返回 JWT token。"""
        import hashlib
        # 前端会对密码进行 SHA-256 哈希
        password_hash = hashlib.sha256("password123".encode()).hexdigest()
        response = await client.post(
            "/auth/login",
            json={"email": "test@nju.edu.cn", "password": password_hash},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user):
        """错误密码应返回 401。"""
        response = await client.post(
            "/auth/login",
            json={"email": "test@nju.edu.cn", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        """不存在用户应返回 401。"""
        response = await client.post(
            "/auth/login",
            json={"email": "nobody@nju.edu.cn", "password": "password123"},
        )
        assert response.status_code == 401
