"""可信请求元数据解析的单一事实源。

对外提供两个入口，共用同一套解析逻辑：
- ``get_client_ip(request)``：路由/依赖里已有 ``Request`` 对象时使用。
- ``get_client_ip_from_scope(scope)``：纯 ASGI 中间件里使用，免去构造 ``Request``。
"""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from fastapi import Request
from starlette.datastructures import Headers

from app.core.config import settings


def _networks(trusted_proxies: Optional[Sequence]) -> tuple:
    """解析可信代理网段。

    未显式传入时用 Settings 里**启动时已解析好**的结果——这个函数在每个请求上都会
    被调用，不能每次重新 ip_network() 解析一遍配置字符串。
    """
    if trusted_proxies is None:
        return settings.trusted_proxy_networks
    return tuple(trusted_proxies)


def _resolve_client_ip(peer: str, headers: Mapping[str, str], networks: tuple) -> str:
    """核心解析：仅当对端本身是可信代理时，才采纳其写入的转发头。"""
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer

    if not any(peer_ip in network for network in networks):
        return peer

    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        chain = [item.strip() for item in forwarded.split(",") if item.strip()]
        chain.append(peer)
        # 从右往左找第一个不属于可信代理网段的地址 = 真实客户端
        for candidate in reversed(chain):
            try:
                candidate_ip = ip_address(candidate)
            except ValueError:
                continue
            if any(candidate_ip in network for network in networks):
                continue
            return str(candidate_ip)

    real_ip = headers.get("x-real-ip")
    if real_ip:
        try:
            return str(ip_address(real_ip.strip()))
        except ValueError:
            pass
    return peer


def get_client_ip(request: Request, trusted_proxies: Optional[Sequence] = None) -> str:
    """返回可信客户端 IP；仅采纳可信代理写入的转发头。"""
    peer = request.client.host if request.client else "unknown"
    return _resolve_client_ip(peer, request.headers, _networks(trusted_proxies))


def get_client_ip_from_scope(
    scope: MutableMapping[str, Any], trusted_proxies: Optional[Sequence] = None
) -> str:
    """同 ``get_client_ip``，但直接从 ASGI scope 解析（纯 ASGI 中间件用）。"""
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    return _resolve_client_ip(
        str(peer), Headers(scope=scope), _networks(trusted_proxies)
    )


def get_client_meta(request: Request) -> dict:
    """返回审计和异常日志共用的可信客户端元数据。"""
    client_ip = get_client_ip(request)
    return {
        "ip_address": None if client_ip == "unknown" else client_ip,
        "user_agent": request.headers.get("user-agent"),
    }
