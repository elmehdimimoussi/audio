"""
Unit tests for Telegram file downloader module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.download_telegram_file import (
    download_telegram_file,
    sanitize_telegram_error,
    validate_file_id,
)


def test_validate_file_id():
    assert validate_file_id("valid_file_id_123-abc") == "valid_file_id_123-abc"
    with pytest.raises(ValueError):
        validate_file_id("")
    with pytest.raises(ValueError):
        validate_file_id("file_id_with_spaces and $pecial!")
    with pytest.raises(ValueError):
        validate_file_id("a" * 501)


def test_sanitize_telegram_error():
    token = "123456:ABC-DEF1234ghIkl-zyx57"
    msg = f"HTTP Error GET https://api.telegram.org/bot{token}/getFile failed"
    clean = sanitize_telegram_error(msg, token)
    assert token not in clean
    assert "bot[REDACTED_TOKEN]" in clean


@patch("requests.get")
def test_download_telegram_file_success(mock_get, tmp_path):
    token = "999999:TEST_BOT_TOKEN"
    target_file = tmp_path / "test_output.audio"

    # Mock getFile response
    get_file_resp = MagicMock()
    get_file_resp.status_code = 200
    get_file_resp.json.return_value = {
        "ok": True,
        "result": {
            "file_id": "file_123",
            "file_path": "voice/file_0.ogg",
            "file_size": 100,
        },
    }

    # Mock stream response
    stream_resp = MagicMock()
    stream_resp.status_code = 200
    stream_resp.iter_content.return_value = [b"mock audio chunk 1 ", b"mock audio chunk 2"]
    stream_resp.__enter__.return_value = stream_resp

    mock_get.side_effect = [get_file_resp, stream_resp]

    result_path = download_telegram_file(
        file_id="file_123",
        output_path=target_file,
        bot_token=token,
        max_bytes=1000,
    )

    assert result_path.exists()
    assert result_path.read_bytes() == b"mock audio chunk 1 mock audio chunk 2"


@patch("requests.get")
def test_download_telegram_file_oversized_rejected(mock_get, tmp_path):
    token = "999999:TEST_BOT_TOKEN"
    target_file = tmp_path / "test_output.audio"

    get_file_resp = MagicMock()
    get_file_resp.status_code = 200
    get_file_resp.json.return_value = {
        "ok": True,
        "result": {
            "file_id": "file_123",
            "file_path": "voice/file_0.ogg",
            "file_size": 2000,  # Exceeds max_bytes=1000
        },
    }

    mock_get.return_value = get_file_resp

    with pytest.raises(ValueError) as excinfo:
        download_telegram_file(
            file_id="file_123",
            output_path=target_file,
            bot_token=token,
            max_bytes=1000,
        )

    assert "exceeds limit" in str(excinfo.value)
