"""email 校验一致性测试（P1-3 子项②：补测试盲区，不改宽松约定）。

背景：email 校验在 schema 层有两套分工，均为有意设计：
- 输入侧（`UserBase` / `RegisterRequest` / `ResetRequestCreate` 等）：`EmailStr` 强格式
  + `validate_email_length` 长度上限（MAX_EMAIL_LENGTH=100），格式与长度双保险。
- 输出侧（`UserOut.email: str`）：**仅长度校验、不强制格式**——历史/测试数据可能使用
  保留域名（@test.local、@example），若改回 `EmailStr` 会让管理员用户列表因 422 变空。

本文件锁定这两套行为，作为回归护栏：任何人把 `UserOut.email` 误改成 `EmailStr`，
或把长度上限逻辑改坏，都会在此失败。
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest, UserBase, UserOut
from app.schemas.password_reset import ResetRequestCreate

VALID_EMAIL = "user@example.com"
# 合法格式但 > 100 字符（90 + "@example.com" = 101），用于触发长度上限。
OVER_LONG_EMAIL = "a" * 90 + "@example.com"


# ---- 输出侧：UserOut（str，仅长度，宽松格式） ----


def test_user_out_accepts_valid_email():
    out = UserOut(
        id=1,
        username="alice",
        email=VALID_EMAIL,
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert out.email == VALID_EMAIL


def test_user_out_rejects_overlong_email():
    with pytest.raises(ValidationError):
        UserOut(
            id=1,
            username="alice",
            email=OVER_LONG_EMAIL,
            is_active=True,
            is_superuser=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )


def test_user_out_accepts_malformed_short_email_lenient():
    """宽松约定护栏：短且格式非法的 email（如保留域名/历史脏数据）不得被拒。"""
    out = UserOut(
        id=1,
        username="alice",
        email="not-an-email",
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert out.email == "not-an-email"


# ---- 输入侧：EmailStr + 长度上限 ----


def test_user_base_accepts_valid_email():
    user = UserBase(username="alice", email=VALID_EMAIL)
    assert user.email == VALID_EMAIL


def test_user_base_rejects_overlong_email():
    with pytest.raises(ValidationError):
        UserBase(username="alice", email=OVER_LONG_EMAIL)


def test_user_base_rejects_malformed_email():
    with pytest.raises(ValidationError):
        UserBase(username="alice", email="not-an-email")


def test_register_request_enforces_length_and_format():
    # 合法
    ok = RegisterRequest(email=VALID_EMAIL, password="Abcd123!", code="123456")
    assert ok.email == VALID_EMAIL
    # 超长（格式合法但超 100 字符）
    with pytest.raises(ValidationError):
        RegisterRequest(email=OVER_LONG_EMAIL, password="Abcd123!", code="123456")
    # 格式非法
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="Abcd123!", code="123456")


def test_reset_request_create_enforces_length_and_format():
    assert ResetRequestCreate(email=VALID_EMAIL).email == VALID_EMAIL
    with pytest.raises(ValidationError):
        ResetRequestCreate(email=OVER_LONG_EMAIL)
    with pytest.raises(ValidationError):
        ResetRequestCreate(email="not-an-email")
