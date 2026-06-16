"""
Redis 客户端（可选）

仅在配置了 settings.REDIS_URL 时才真正创建连接；未配置时所有接口返回 None，
调用方据此走纯内存逻辑，不会触发 redis 依赖的导入与连接。
"""

from app.core.config import settings
from app.core.loguru_logger import get_logger

logger = get_logger("redis")

_redis_client = None  # type: ignore[var-annotated]
_initialized = False


def get_redis_client():
    """获取全局 Redis 异步客户端；未配置 REDIS_URL 时返回 None。

    注意：仅创建客户端对象，不会在此处建立/校验连接。
    连接的真实可用性由调用方在使用时感知并降级（见 DegradableRateLimiter）。
    """
    global _redis_client, _initialized

    if _initialized:
        return _redis_client

    _initialized = True

    if not settings.REDIS_URL:
        logger.info("未配置 REDIS_URL，限流/缓存使用纯内存模式")
        _redis_client = None
        return None

    try:
        from redis.asyncio import from_url

        _redis_client = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        )
        logger.info("Redis 客户端已创建", url=_mask_url(settings.REDIS_URL))
    except ImportError:
        logger.error("已配置 REDIS_URL 但未安装 redis 包，请执行 pip install redis；本次回退为内存模式")
        _redis_client = None
    except Exception as e:  # noqa: BLE001 - 创建失败不应阻断应用启动
        logger.error("Redis 客户端创建失败，回退为内存模式", error=str(e))
        _redis_client = None

    return _redis_client


async def ping_redis() -> bool:
    """主动探测 Redis 连通性（用于启动日志/健康检查）。失败返回 False，不抛异常。"""
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis ping 失败", error=str(e))
        return False


async def close_redis_client() -> None:
    """应用关闭时释放连接。"""
    global _redis_client, _initialized
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _initialized = False


def _mask_url(url: str) -> str:
    """隐去 URL 中的密码用于日志。"""
    if "@" not in url:
        return url
    head, tail = url.rsplit("@", 1)
    if ":" in head:
        scheme_user = head.rsplit(":", 1)[0]
        return f"{scheme_user}:***@{tail}"
    return f"***@{tail}"
