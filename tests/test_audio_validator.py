"""
Unit tests for audio_validator.py
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.audio_validator import format_duration, validate_audio_file


def test_format_duration():
    assert format_duration(0) == "00:00:00"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(7200) == "02:00:00"


def test_validate_nonexistent_file():
    with pytest.raises(FileNotFoundError, match="Media file does not exist"):
        validate_audio_file("/non/existent/path/audio.mp3")


def test_validate_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
        with pytest.raises(ValueError, match="Media file is empty"):
            validate_audio_file(tmp.name)


@patch("src.audio_validator.run_ffprobe")
def test_validate_valid_audio(mock_ffprobe):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"dummy audio content")
        tmp_path = Path(tmp.name)

    try:
        mock_ffprobe.return_value = {
            "format": {
                "duration": "120.5",
                "format_name": "mp3",
                "size": "1024",
            },
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": 2,
                }
            ],
        }

        metadata = validate_audio_file(tmp_path)
        assert metadata.duration_seconds == 120.5
        assert metadata.duration_formatted in ("00:02:00", "00:02:01")
        assert metadata.audio_codec == "mp3"
        assert metadata.container_format == "mp3"
        assert metadata.sample_rate == 44100
        assert metadata.channels == 2
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@patch("src.audio_validator.run_ffprobe")
def test_validate_no_audio_stream(mock_ffprobe):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(b"video only content")
        tmp_path = Path(tmp.name)

    try:
        mock_ffprobe.return_value = {
            "format": {"duration": "10.0"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
        }

        with pytest.raises(ValueError, match="contains no audio stream"):
            validate_audio_file(tmp_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@patch("src.audio_validator.run_ffprobe")
def test_validate_exceeds_duration(mock_ffprobe):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"long audio content")
        tmp_path = Path(tmp.name)

    try:
        # 3 hours = 10800s, max_duration=7200s, tolerance=60s -> allowed 7260s
        mock_ffprobe.return_value = {
            "format": {"duration": "10800.0", "format_name": "mp3"},
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
        }

        with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
            validate_audio_file(tmp_path, max_duration_seconds=7200, tolerance_seconds=60)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
