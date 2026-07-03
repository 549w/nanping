"""邮件发送模块。

使用 Resend API 发送事务邮件（验证码等）。
Resend SDK 是同步的，通过 asyncio.to_thread 包装为异步调用。
"""

import asyncio

import resend

from .config import settings


async def send_email(to: str, subject: str, html: str) -> None:
    """发送一封 HTML 邮件。

    Args:
        to: 收件人邮箱地址。
        subject: 邮件主题。
        html: HTML 格式的邮件正文。

    Raises:
        RuntimeError: 发送失败时抛出，调用方应捕获并记录日志。
    """
    resend.api_key = settings.RESEND_API_KEY

    try:
        await asyncio.to_thread(
            resend.Emails.send,
            {
                "from": f"Nanping <{settings.SENDER_EMAIL}>",
                "to": [to],
                "subject": subject,
                "html": html,
            },
        )
    except Exception as exc:
        raise RuntimeError(f"邮件发送失败 (to={to}): {exc}") from exc


async def send_verification_code(email: str, code: str) -> None:
    """发送注册验证码邮件。

    Args:
        email: 收件人邮箱。
        code: 6 位验证码。
    """
    await send_email(
        to=email,
        subject="Nanping 注册验证码",
        html=f"""\
<div style="max-width:480px;margin:0 auto;font-family:sans-serif;">
  <h2 style="color:#6B1C6C;">Nanping 南评</h2>
  <p>你的注册验证码为：</p>
  <div style="font-size:32px;font-weight:bold;letter-spacing:6px;text-align:center;
              padding:20px;background:#f5f0f5;border-radius:8px;color:#6B1C6C;">
    {code}
  </div>
  <p style="color:#888;margin-top:24px;">验证码 5 分钟内有效，请勿转发给他人。</p>
  <p style="color:#888;">如果这不是你本人的操作，请忽略此邮件。</p>
</div>""",
    )
