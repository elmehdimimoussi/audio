"""
Unit tests for downloader.py
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

try:
    import requests
except ImportError:
    class MockRequestException(Exception): pass
    mock_req = MagicMock()
    mock_req.exceptions.RequestException = MockRequestException
    sys.modules["requests"] = mock_req

from src.downloader import (
    determine_file_extension,
    download_file,
    sanitize_url_for_logging,
    transform_google_drive_url,
)


def test_transform_google_drive_url():
    # User's exact Google Drive sharing link format
    gdrive_url = "https://drive.google.com/file/d/0B4nRO6znZNtoc1U3ZzdaaVlvcjg/view?usp=sharing&resourcekey=0-ij-QmPBxTyuMKyl4CmVyjQ"
    transformed = transform_google_drive_url(gdrive_url)
    
    assert "export=download" in transformed
    assert "id=0B4nRO6znZNtoc1U3ZzdaaVlvcjg" in transformed
    assert "resourcekey=0-ij-QmPBxTyuMKyl4CmVyjQ" in transformed
    assert transformed.startswith("https://drive.google.com/uc?")

    # Standard non-drive URL remains unchanged
    normal_url = "https://example.com/audio.mp3"
    assert transform_google_drive_url(normal_url) == normal_url


def test_sanitize_url_for_logging():
    assert sanitize_url_for_logging("") == ""
    
    # Credentials and query parameters masked
    url_with_auth = "https://user:password@example.com/audio.mp3?token=secret123&key=val"
    sanitized = sanitize_url_for_logging(url_with_auth)
    
    assert "user" not in sanitized
    assert "password" not in sanitized
    assert "secret123" not in sanitized
    assert "token=***" in sanitized
    assert "key=***" in sanitized
    assert sanitized.startswith("https://example.com/audio.mp3")


def test_determine_file_extension():
    assert determine_file_extension("https://example.com/file.mp3") == ".mp3"
    assert determine_file_extension("https://example.com/file.wav") == ".wav"
    assert determine_file_extension("https://example.com/file", content_type="audio/mpeg") == ".mp3"
    assert determine_file_extension("https://example.com/file.xyz") == ".media"


def test_download_file_rejects_http():
    with pytest.raises(ValueError, match="Only HTTPS URLs are allowed"):
        download_file("http://insecure-example.com/audio.mp3", "/tmp")


def test_download_file_rejects_empty_url():
    with pytest.raises(ValueError, match="Audio URL must not be empty"):
        download_file("", "/tmp")


@patch("src.downloader.sanitize_url_for_logging")
def test_download_file_enforces_size_limit(mock_sanitize):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.history = []
    mock_response.headers = {"Content-Length": "50000"}
    mock_response.iter_content = MagicMock(return_value=[b"x" * 1000 for _ in range(50)])

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    try:
        import requests
        with patch("requests.Session", return_value=mock_session):
            with tempfile.TemporaryDirectory() as tmp_dir:
                with pytest.raises(ValueError, match="exceeds max allowed size"):
                    download_file("https://example.com/audio.mp3", tmp_dir, max_bytes=10000)
    except ImportError:
        with patch("sys.modules", dict(sys.modules)):
            mock_req_module = MagicMock()
            mock_req_module.Session.return_value = mock_session
            class RealRequestException(Exception): pass
            mock_req_module.exceptions.RequestException = RealRequestException
            sys.modules["requests"] = mock_req_module
            with tempfile.TemporaryDirectory() as tmp_dir:
                with pytest.raises(ValueError, match="exceeds max allowed size"):
                    download_file("https://example.com/audio.mp3", tmp_dir, max_bytes=10000)
