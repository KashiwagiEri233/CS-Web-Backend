"""邮件发送服务：smtplib 线程池发送，未配置 SMTP_HOST 时回退控制台输出。

与前端行为对齐：SMTP_HOST 为空 = 开发模式，验证码输出到控制台（见 verification_service）。
支持 HTML 邮件：`send_mail(..., html=...)` 时构造 multipart/alternative
（纯文本回退 + HTML），保证无 HTML 能力的客户端与送达率。
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Union

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


def _build_message(
    to: str, subject: str, text: str, html: Optional[str] = None
) -> Union[MIMEText, MIMEMultipart]:
    """构造待发送的 MIME 消息（纯文本，或纯文本 + HTML 的 alternative）。"""
    msg: Union[MIMEText, MIMEMultipart]
    if html is None:
        msg = MIMEText(text, "plain", "utf-8")
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    return msg


def _send_sync(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
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
        msg = _build_message(to, subject, text, html)
        transport.sendmail(settings.SMTP_FROM, [to], msg.as_string())
    finally:
        try:
            transport.quit()
        except Exception:  # noqa: BLE001 - 关闭失败不掩盖发送结果
            pass


async def send_mail(
    to: str, subject: str, text: str, html: Optional[str] = None
) -> None:
    """发送邮件（异步封装）。SMTP_HOST 为空时仅记日志。

    QUEUE_ENABLED=True 时经 arq 队列异步发送（含自动重试）；
    否则在线程池中同步发送（失败抛异常由调用方兜底）。
    """
    if _queue_enabled():
        from app.core.queue import enqueue
        from app.core.queue.tasks import send_email_task

        await enqueue(send_email_task, to, subject, text, html)
        return
    await asyncio.to_thread(_send_sync, to, subject, text, html)


def _queue_enabled() -> bool:
    """读取队列开关（与 queue/client.py 同源，但延迟 import 避免循环依赖）。"""
    import os

    val = os.getenv("QUEUE_ENABLED")
    if val is None:
        try:
            from dotenv import dotenv_values

            env_file = os.environ.get("ENV_FILE", ".env")
            val = dotenv_values(env_file).get("QUEUE_ENABLED")
        except Exception:  # noqa: BLE001
            val = None
    return (
        str(val).strip().lower() in ("1", "true", "yes", "on")
        if val is not None
        else False
    )


async def send_verification_code(email: str, code: str) -> None:
    """发送注册/找回密码验证码邮件（HTML 模板 + 纯文本回退，与前端文案一致）。"""
    from app.core.timezone import now_utc
    from app.services.email_templates import render_template

    subject = "【FZTBU】验证码"
    text = f"""您的验证码是：{code}

验证码有效期为 {settings.VERIFICATION_CODE_TTL_MINUTES} 分钟，请尽快完成操作。

如非本人操作，请忽略此邮件。"""
    html = render_template(
        "verification_code.html",
        code=code,
        ttl_minutes=settings.VERIFICATION_CODE_TTL_MINUTES,
        year=now_utc().year,
    )
    await send_mail(email, subject, text, html=html)
