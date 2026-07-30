"""
Unit tests for subtitle_writer.py
"""

import json
import tempfile
from pathlib import Path
import pytest

from src.subtitle_writer import (
    format_timestamp_srt,
    format_timestamp_vtt,
    generate_json,
    generate_srt,
    generate_txt,
    generate_vtt,
    write_transcripts,
)


def test_format_timestamp_srt():
    assert format_timestamp_srt(0.0) == "00:00:00,000"
    assert format_timestamp_srt(1.234) == "00:00:01,234"
    assert format_timestamp_srt(65.5) == "00:01:05,500"
    # Long duration > 1 hour
    assert format_timestamp_srt(4530.123) == "01:15:30,123"
    # Negative values clamped to 0
    assert format_timestamp_srt(-10.0) == "00:00:00,000"


def test_format_timestamp_vtt():
    assert format_timestamp_vtt(0.0) == "00:00:00.000"
    assert format_timestamp_vtt(1.234) == "00:00:01.234"
    assert format_timestamp_vtt(4530.123) == "01:15:30.123"


def test_generate_txt():
    segments = [
        {"text": "  مرحبا بكم في هذا التسجيل.  "},
        {"text": "هذا اختبار للذكاء الاصطناعي."},
    ]
    txt_output = generate_txt(segments)
    assert "مرحبا بكم في هذا التسجيل." in txt_output
    assert "هذا اختبار للذكاء الاصطناعي." in txt_output
    assert "\n\n" in txt_output


def test_generate_srt():
    segments = [
        {"start": 0.0, "end": 2.5, "text": "مرحبا بكم"},
        {"start": 2.5, "end": 5.123, "text": "Welcome to the test"},
    ]
    srt = generate_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:02,500\nمرحبا بكم" in srt
    assert "2\n00:00:02,500 --> 00:00:05,123\nWelcome to the test" in srt


def test_generate_vtt():
    segments = [
        {"start": 0.0, "end": 2.5, "text": "مرحبا بكم"},
    ]
    vtt = generate_vtt(segments)
    assert vtt.startswith("WEBVTT\n")
    assert "1\n00:00:00.000 --> 00:00:02.500\nمرحبا بكم" in vtt


def test_generate_json_structure_and_unicode():
    source_info = {"file": "test.mp3", "file_size_bytes": 1024}
    metadata = {
        "model": "small",
        "requested_language": "ar",
        "detected_language": "ar",
        "language_probability": 0.99,
        "duration_seconds": 10.0,
        "processing_seconds": 2.5,
    }
    segments = [
        {
            "id": 0,
            "start": 0.0,
            "end": 2.5,
            "text": "مرحبا بك",
            "words": [{"start": 0.0, "end": 1.0, "word": "مرحبا", "probability": 0.98}],
        }
    ]

    json_str = generate_json(source_info, metadata, segments, include_words=True)
    data = json.loads(json_str)

    assert data["source"]["file"] == "test.mp3"
    assert data["transcription"]["model"] == "small"
    assert data["transcription"]["detected_language"] == "ar"
    assert len(data["transcription"]["segments"]) == 1

    seg = data["transcription"]["segments"][0]
    assert seg["text"] == "مرحبا بك"
    assert len(seg["words"]) == 1
    assert seg["words"][0]["word"] == "مرحبا"

    # Ensure Arabic text is kept raw UTF-8, not escaped \uXXXX
    assert "مرحبا بك" in json_str
    assert r"\u0645" not in json_str


def test_generate_json_without_words():
    segments = [
        {
            "id": 0,
            "start": 0.0,
            "end": 2.5,
            "text": "Hello world",
            "words": [{"start": 0.0, "end": 1.0, "word": "Hello", "probability": 0.95}],
        }
    ]
    json_str = generate_json({}, {}, segments, include_words=False)
    data = json.loads(json_str)
    assert "words" not in data["transcription"]["segments"][0]


def test_write_transcripts():
    segments = [{"start": 0.0, "end": 1.0, "text": "Test paragraph"}]
    with tempfile.TemporaryDirectory() as tmp_dir:
        written = write_transcripts(
            output_dir=tmp_dir,
            base_filename="sample",
            segments=segments,
            requested_formats=["txt", "srt", "vtt", "json"],
        )

        assert "txt" in written and written["txt"].exists()
        assert "srt" in written and written["srt"].exists()
        assert "vtt" in written and written["vtt"].exists()
        assert "json" in written and written["json"].exists()
