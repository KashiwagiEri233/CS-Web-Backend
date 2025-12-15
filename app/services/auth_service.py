from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password, create_access_token
from app.core.config import settings
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import Token


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
    
    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """验证用户凭据"""
        user = await self.user_repo.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
    
    async def create_token_for_user(self, user: User) -> Token:
        """为用户创建访问令牌"""
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username, "id": user.id},
            expires_delta=access_token_expires,
        )
        return Token(access_token=access_token, token_type="bearer")
    
    async def get_current_user(self, token: str) -> Optional[User]:
        """通过令牌获取当前用户"""
        from app.core.security import verify_token
        
        payload = verify_token(token)
        if payload is None:
            return None
        
        username: str = payload.get("sub")
        if username is None:
            return None
            
        user = await self.user_repo.get_by_username(username)
        return user
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """通过ID获取用户"""
        return await self.user_repo.get_by_id(user_id)
    
    async def create_user(self, user_data):
        """创建新用户"""
        from app.core.security import get_password_hash
        from app.schemas.auth import UserCreate
        from app.models.user import User
        
        # 检查是否已存在相同用户名或邮箱的用户
        if await self.user_repo.get_by_username(user_data.username):
            raise ValueError("用户名已存在")
        
        if await self.user_repo.get_by_email(user_data.email):
            raise ValueError("邮箱已存在")
        
        # 创建新用户
        hashed_password = get_password_hash(user_data.password)
        user_dict = {
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "is_active": True
        }
        
        return await self.user_repo.create(user_dict)