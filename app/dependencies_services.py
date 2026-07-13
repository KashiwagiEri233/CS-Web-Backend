"""Service 层 Depends 工厂：统一从请求级 AsyncSession 构造 service。

用法::

    from app.dependencies_services import get_user_service

    async def endpoint(svc: UserService = Depends(get_user_service)):
        ...
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.exception_service import ExceptionService
from app.services.rbac_service import RBACService
from app.services.user_service import UserService


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_rbac_service(db: AsyncSession = Depends(get_db)) -> RBACService:
    return RBACService(db)


def get_exception_service(db: AsyncSession = Depends(get_db)) -> ExceptionService:
    return ExceptionService(db)


def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(db)
