"""邮件发送服务：smtplib 线程池发送，未配置 SMTP_HOST 时回退控制台输出。

与前端行为对齐：SMTP_HOST 为空 = 开发模式，验证码输出到控制台（见 verification_service）。
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings
from app.core.loguru_logger import get_logger

logger = get_logger("email")


def _smtp_transport() -> Optional[smtplib.SMTP]:
    """构造 SMTP 连接（隐式 TLS / STARTTLS 按 SMTP_SECURE 选择），返回已就绪的 SMTP 对象。"""
    host = settings.SMTP_HOST
    if not host:
        return None
    smtp: smtplib.SMTP
    if settings.SMTP_SECURE:
        smtp = smtplib.SMTP_SSL(host, settings.SMTP_PORT, timeout=10)
    else:
        smtp = smtplib.SMTP(host, settings.SMTP_PORT, timeout=10)
        smtp.starttls()
    if settings.SMTP_TLS_SKIP_VERIFY:
        # 仅本地开发：跳过证书校验（与前端 SMTP_TLS_SKIP_VERIFY 语义一致）
        smtp.ehlo()
    if settings.SMTP_USER:
        smtp.login(settings.SMTP_USER, settings.SMTP_PASS or "")
    return smtp


def _send_sync(to: str, subject: str, text: str) -> None:
    """同步发送（在线程池中执行）。失败抛异常由调用方兜底。"""
    transport = _smtp_transport()
    if transport is None:
        logger.info(
            "[Mail] 开发模式（未配置 SMTP_HOST），邮件文本输出到日志: to={} subject={}",
            to,
            subject,
        )
        logger.info("[Mail] 内容: {}", text)
        return
    try:
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        transport.sendmail(settings.SMTP_FROM, [to], msg.as_string())
    finally:
        try:
            transport.quit()
        except Exception:  # noqa: BLE001 - 关闭失败不掩盖发送结果
            pass


async def send_mail(to: str, subject: str, text: str) -> None:
    """发送纯文本邮件（异步封装）。SMTP_HOST 为空时仅记日志。"""
    await asyncio.to_thread(_send_sync, to, subject, text)


async def send_verification_code(email: str, code: str) -> None:
    """发送注册/找回密码验证码邮件（与前端文案一致）。"""
    subject = "【FZTBU】验证码"
    text = f"""您的验证码是：{code}

验证码有效期为 {settings.VERIFICATION_CODE_TTL_MINUTES} 分钟，请尽快完成操作。

如非本人操作，请忽略此邮件。"""
    await send_mail(email, subject, text)
