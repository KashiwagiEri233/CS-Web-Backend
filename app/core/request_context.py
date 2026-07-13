"""可信请求元数据解析的单一事实源。"""

from __future__ import annotations

from ipaddress import ip_address
from typing import Optional, Sequence

from fastapi import Request

from app.core.config import settings


def get_client_ip(request: Request, trusted_proxies: Optional[Sequence] = None) -> str:
    """返回可信客户端 IP；仅采纳可信代理写入的转发头。"""
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer

    networks = (
        settings.trusted_proxy_networks
        if trusted_proxies is None
        else tuple(trusted_proxies)
    )
    if not any(peer_ip in network for network in networks):
        return peer

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        chain = [item.strip() for item in forwarded.split(",") if item.strip()]
        chain.append(peer)
        for candidate in reversed(chain):
            try:
                candidate_ip = ip_address(candidate)
            except ValueError:
                continue
            if any(candidate_ip in network for network in networks):
                continue
            return str(candidate_ip)

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        try:
            return str(ip_address(real_ip.strip()))
        except ValueError:
            pass
    return peer


def get_client_meta(request: Request) -> dict:
    """返回审计和异常日志共用的可信客户端元数据。"""
    client_ip = get_client_ip(request)
    return {
        "ip_address": None if client_ip == "unknown" else client_ip,
        "user_agent": request.headers.get("user-agent"),
    }
