"""
Unit tests for Telegram media extraction and caption parsing module.
"""

import pytest

from telegram_bot.media import extract_media_info, parse_caption_options


def test_extract_audio_message():
    update = {
        "update_id": 1001,
        "message": {
            "message_id": 42,
            "from": {"id": 12345, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 67890, "type": "private"},
            "audio": {
                "file_id": "audio_file_id_123",
                "file_unique_id": "uniq_123",
                "file_size": 1024000,
                "duration": 120,
                "mime_type": "audio/mpeg",
                "file_name": "sample.mp3",
            },
            "caption": "language=en model=base",
        },
    }

    media, err = extract_media_info(update)
    assert err is None
    assert media is not None
    assert media.file_id == "audio_file_id_123"
    assert media.media_type == "audio"
    assert media.user_id == 12345
    assert media.chat_id == 67890
    assert media.message_id == 42
    assert media.caption == "language=en model=base"


def test_extract_voice_message():
    update = {
        "update_id": 1002,
        "message": {
            "message_id": 43,
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": 67890, "type": "private"},
            "voice": {
                "file_id": "voice_file_id_456",
                "file_unique_id": "uniq_456",
                "file_size": 51200,
                "duration": 15,
                "mime_type": "audio/ogg",
            },
        },
    }

    media, err = extract_media_info(update)
    assert err is None
    assert media is not None
    assert media.file_id == "voice_file_id_456"
    assert media.media_type == "voice"


def test_extract_unsupported_document():
    update = {
        "update_id": 1003,
        "message": {
            "message_id": 44,
            "from": {"id": 12345},
            "chat": {"id": 67890, "type": "private"},
            "document": {
                "file_id": "doc_789",
                "file_unique_id": "uniq_789",
                "file_size": 100,
                "file_name": "script.exe",
                "mime_type": "application/x-msdownload",
            },
        },
    }

    media, err = extract_media_info(update)
    assert media is None
    assert "Unsupported document format" in err


def test_extract_supported_document():
    update = {
        "update_id": 1004,
        "message": {
            "message_id": 45,
            "from": {"id": 12345},
            "chat": {"id": 67890, "type": "private"},
            "document": {
                "file_id": "doc_wav_101",
                "file_unique_id": "uniq_101",
                "file_size": 2048000,
                "file_name": "interview.wav",
                "mime_type": "audio/wav",
            },
        },
    }

    media, err = extract_media_info(update)
    assert err is None
    assert media is not None
    assert media.file_id == "doc_wav_101"
    assert media.media_type == "document"


def test_parse_caption_options():
    caption = (
        "language=fr\n"
        "model=medium\n"
        "formats=txt,srt\n"
        "prompt=Technical terminology"
    )

    opts = parse_caption_options(caption, default_lang="ar", default_model="small")
    assert opts.language == "fr"
    assert opts.model == "medium"
    assert opts.output_formats == "txt,srt"
    assert opts.initial_prompt == "Technical terminology"


def test_parse_caption_options_defaults():
    opts = parse_caption_options("")
    assert opts.language == "ar"
    assert opts.model == "medium"
    assert opts.output_formats == "txt"
    assert opts.initial_prompt == ""
