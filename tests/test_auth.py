"""Unit tests for api/auth.py — no DB or network needed."""
import pytest
from fastapi import HTTPException

import api.auth as auth_module
from api.auth import require_api_key


def test_no_op_when_api_key_unset(monkeypatch):
    monkeypatch.setattr(auth_module, "API_KEY", "")
    require_api_key(x_api_key=None)  # must not raise


def test_rejects_missing_header_when_api_key_set(monkeypatch):
    monkeypatch.setattr(auth_module, "API_KEY", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401


def test_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(auth_module, "API_KEY", "secret123")
    with pytest.raises(HTTPException):
        require_api_key(x_api_key="wrong")


def test_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(auth_module, "API_KEY", "secret123")
    require_api_key(x_api_key="secret123")  # must not raise
