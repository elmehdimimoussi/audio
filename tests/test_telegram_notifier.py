"""
Unit tests for Telegram Notifier module.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.telegram_notifier import (
    TelegramNotifier,
    sanitize_telegram_error,
    validate_chat_id,
    validate_message_id,
)


def test_validate_ids():
    assert validate_chat_id("123456789") == 123456789
    assert validate_chat_id("-1009876543210") == -1009876543210
    with pytest.raises(ValueError):
        validate_chat_id("not_an_int")

    assert validate_message_id("42") == 42
    assert validate_message_id(None) is None
    assert validate_message_id("") is None
    with pytest.raises(ValueError):
        validate_message_id("-5")


def test_sanitize_telegram_error():
    token = "888888:SECRET_TOKEN_ABC"
    err_text = f"Request to https://api.telegram.org/bot{token}/sendMessage failed"
    clean = sanitize_telegram_error(err_text, token)
    assert token not in clean
    assert "bot[REDACTED_TOKEN]" in clean


@patch("requests.post")
def test_send_transcription_outputs(mock_post, tmp_path):
    token = "888888:SECRET_TOKEN_ABC"
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    (out_dir / "transcript.txt").write_text("Plain text transcript", encoding="utf-8")
    (out_dir / "transcript.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello", encoding="utf-8")
    (out_dir / "transcript.json").write_text(
        json.dumps({
            "transcription": {
                "model": "small",
                "detected_language": "ar",
                "duration_seconds": 12.5,
                "processing_seconds": 1.2,
            }
        }),
        encoding="utf-8"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 100}}
    mock_post.return_value = mock_resp

    notifier = TelegramNotifier(bot_token=token)
    sent_count = notifier.send_transcription_outputs(
        chat_id=12345,
        output_dir=out_dir,
        status_message_id=99,
    )

    assert sent_count == 3
    assert mock_post.call_count >= 2


@patch("requests.post")
def test_send_failure_notification(mock_post):
    token = "888888:SECRET_TOKEN_ABC"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 101}}
    mock_post.return_value = mock_resp

    notifier = TelegramNotifier(bot_token=token)
    notifier.send_failure_notification(
        chat_id=12345,
        request_id="123e4567-e89b-12d3-a456-426614174000",
        stage="ffprobe validation",
        status_message_id=99,
    )

    mock_post.assert_called_once()
    payload = mock_post.call_args[1]["data"]
    assert payload["chat_id"] == 12345
    assert payload["message_id"] == 99
    assert "Transcription Failed" in payload["text"]
    assert "ffprobe validation" in payload["text"]
