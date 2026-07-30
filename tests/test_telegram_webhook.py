"""
Unit tests for FastAPI Telegram Webhook endpoints.
"""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from telegram_bot.app import app, state_mgr
from telegram_bot.state import StateManager

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_temp_state_db(tmp_path):
    """Use isolated temporary SQLite database for each test."""
    temp_db = tmp_path / "test_bot.db"
    new_mgr = StateManager(db_path=temp_db)
    with patch("telegram_bot.app.state_mgr", new_mgr):
        yield


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "telegram-whisper-bot"
    # Ensure no secrets or configuration details are exposed
    assert "token" not in data
    assert "secret" not in data


@patch("telegram_bot.app.settings.TELEGRAM_WEBHOOK_SECRET", "test_secret_123")
def test_webhook_secret_header_verification():
    payload = {"update_id": 9999}

    # Missing secret header -> 403
    resp_missing = client.post("/telegram/webhook", json=payload)
    assert resp_missing.status_code == 403

    # Invalid secret header -> 403
    resp_invalid = client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
    )
    assert resp_invalid.status_code == 403

    # Valid secret header -> 200
    resp_valid = client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_123"},
    )
    assert resp_valid.status_code == 200


@patch("telegram_bot.app.settings.TELEGRAM_WEBHOOK_SECRET", "")
@patch("telegram_bot.app.settings.ALLOWED_TELEGRAM_USER_IDS", "1001,1002")
@patch("telegram_bot.app.telegram_client.send_message", new_callable=AsyncMock)
def test_unauthorized_user_rejected(mock_send):
    mock_send.return_value = (True, 1, "ok")
    payload = {
        "update_id": 8801,
        "message": {
            "message_id": 1,
            "from": {"id": 9999},  # Unauthorized
            "chat": {"id": 9999, "type": "private"},
            "text": "Hello bot",
        },
    }

    resp = client.post("/telegram/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "user_unauthorized"
    mock_send.assert_called_once()
    assert "not authorized" in mock_send.call_args[1]["text"].lower()


@patch("telegram_bot.app.settings.TELEGRAM_WEBHOOK_SECRET", "")
@patch("telegram_bot.app.settings.ALLOWED_TELEGRAM_USER_IDS", "1001")
@patch("telegram_bot.app.telegram_client.send_message", new_callable=AsyncMock)
@patch("telegram_bot.app.github_client.trigger_workflow", new_callable=AsyncMock)
def test_duplicate_update_id_idempotency(mock_trigger, mock_send):
    mock_send.return_value = (True, 55, "ok")
    mock_trigger.return_value = (True, "Dispatched")

    payload = {
        "update_id": 7701,
        "message": {
            "message_id": 10,
            "from": {"id": 1001},
            "chat": {"id": 1001, "type": "private"},
            "audio": {
                "file_id": "file_abc_123",
                "file_unique_id": "u123",
                "file_size": 5000,
                "duration": 10,
            },
        },
    }

    # First delivery
    resp1 = client.post("/telegram/webhook", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "request_dispatched"

    # Second duplicate delivery
    resp2 = client.post("/telegram/webhook", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_update_ignored"
