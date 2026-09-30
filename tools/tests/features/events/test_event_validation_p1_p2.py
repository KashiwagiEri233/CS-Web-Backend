"""Unit tests for Event form validation and registration rules (P1/P2)."""

import pytest
from unittest.mock import MagicMock

from app.core.exceptions import ValidationException
from app.models.event import Event
from app.services.event.event_service import EventService


def test_validate_form_data_success():
    event = MagicMock(spec=Event)
    event.registration_fields = [
        {"key": "qq", "label": "QQ号", "type": "text", "required": True},
        {
            "key": "track",
            "label": "方向",
            "type": "select",
            "required": True,
            "options": ["Web", "AI", "Sec"],
        },
        {"key": "note", "label": "备注", "type": "textarea", "required": False},
    ]

    # Valid data
    valid_data = {"qq": "12345678", "track": "AI", "note": "Hello"}
    EventService._validate_form_data(event, valid_data)


def test_validate_form_data_missing_required():
    event = MagicMock(spec=Event)
    event.registration_fields = [
        {"key": "qq", "label": "QQ号", "type": "text", "required": True},
    ]

    with pytest.raises(ValidationException) as exc_info:
        EventService._validate_form_data(event, {"qq": "   "})
    assert "QQ号 为必填项" in str(exc_info.value.message)


def test_validate_form_data_invalid_select_option():
    event = MagicMock(spec=Event)
    event.registration_fields = [
        {
            "key": "track",
            "label": "方向",
            "type": "select",
            "required": True,
            "options": ["Web", "AI"],
        },
    ]

    with pytest.raises(ValidationException) as exc_info:
        EventService._validate_form_data(event, {"track": "InvalidTrack"})
    assert "方向 选项无效" in str(exc_info.value.message)


def test_validate_form_data_too_long():
    event = MagicMock(spec=Event)
    event.registration_fields = [
        {"key": "note", "label": "备注", "type": "textarea", "required": False},
    ]

    with pytest.raises(ValidationException) as exc_info:
        EventService._validate_form_data(event, {"note": "x" * 1001})
    assert "输入内容过长" in str(exc_info.value.message)
