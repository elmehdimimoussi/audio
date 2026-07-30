"""
Telegram media extraction and caption options parser.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    ".opus", ".mp4", ".mov", ".mkv", ".webm",
}

SUPPORTED_MIME_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac",
    "audio/flac", "audio/ogg", "audio/opus", "video/mp4",
    "video/quicktime", "video/x-matroska", "video/webm",
    "application/ogg", "application/octet-stream",
}

SUPPORTED_MODELS = {"tiny", "base", "small", "medium", "large-v3", "turbo"}


@dataclass
class MediaInfo:
    file_id: str
    file_unique_id: str
    file_size: int
    file_name: str
    mime_type: str
    duration: float
    media_type: str
    user_id: int
    chat_id: int
    message_id: int
    caption: str


@dataclass
class TranscriptionOptions:
    language: str = "ar"
    model: str = "medium"
    output_formats: str = "txt"
    initial_prompt: str = ""
    vad_filter: str = "true"
    word_timestamps: str = "true"


def extract_media_info(update_dict: Dict[str, Any]) -> Tuple[Optional[MediaInfo], Optional[str]]:
    """
    Extract media metadata from Telegram update dictionary.
    Returns (MediaInfo, error_message).
    """
    message = update_dict.get("message") or update_dict.get("edited_message")
    if not message:
        return None, "Update contains no message object."

    from_user = message.get("from", {})
    chat = message.get("chat", {})

    user_id = from_user.get("id")
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    caption = (message.get("caption") or "").strip()

    if not user_id or not chat_id or not message_id:
        return None, "Message missing user_id, chat_id, or message_id."

    # Check media fields in order of specificity
    media_type = None
    media_obj = None

    if "audio" in message:
        media_type = "audio"
        media_obj = message["audio"]
    elif "voice" in message:
        media_type = "voice"
        media_obj = message["voice"]
    elif "video" in message:
        media_type = "video"
        media_obj = message["video"]
    elif "video_note" in message:
        media_type = "video_note"
        media_obj = message["video_note"]
    elif "document" in message:
        media_type = "document"
        media_obj = message["document"]

    if not media_type or not media_obj:
        return None, "Message contains no supported media attachment (audio, voice, video, document)."

    file_id = media_obj.get("file_id", "")
    file_unique_id = media_obj.get("file_unique_id", "")
    file_size = media_obj.get("file_size", 0)
    duration = float(media_obj.get("duration", 0.0))
    file_name = media_obj.get("file_name", f"telegram_media_{file_unique_id}")
    mime_type = media_obj.get("mime_type", "").lower()

    if not file_id:
        return None, "Media object missing file_id."

    # Validate document format if document
    if media_type == "document":
        ext = Path(file_name).suffix.lower()
        is_valid_ext = ext in SUPPORTED_EXTENSIONS
        is_valid_mime = mime_type in SUPPORTED_MIME_TYPES

        if not is_valid_ext and not is_valid_mime:
            return None, (
                f"Unsupported document format '{file_name}' (MIME: {mime_type}). "
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

    info = MediaInfo(
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_size=file_size,
        file_name=file_name,
        mime_type=mime_type,
        duration=duration,
        media_type=media_type,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        caption=caption,
    )

    return info, None


def parse_caption_options(
    caption: str,
    default_lang: str = "ar",
    default_model: str = "medium",
    default_formats: str = "txt",
) -> TranscriptionOptions:
    """
    Parse optional caption parameters formatted as key=value lines or space-separated tokens.
    Example:
      language=ar
      model=medium
      formats=txt
      prompt=Vocabulary list
    """
    opts = TranscriptionOptions(language=default_lang, model=default_model, output_formats=default_formats)

    if not caption or not caption.strip():
        return opts

    lines = caption.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or "=" not in line:
            continue

        key, val = line.split("=", 1)
        key = key.strip().lower()
        val = val.strip()

        if key in ("language", "lang"):
            if len(val) <= 10 and val.isalnum():
                opts.language = val.lower()

        elif key in ("model", "whisper_model"):
            if val.lower() in SUPPORTED_MODELS:
                opts.model = val.lower()

        elif key in ("formats", "format", "output_formats"):
            requested = [f.strip().lower() for f in val.split(",") if f.strip()]
            valid_fmts = [f for f in requested if f in ("txt", "srt", "vtt", "json")]
            if valid_fmts:
                opts.output_formats = ",".join(valid_fmts)

        elif key in ("prompt", "initial_prompt"):
            # Enforce strict maximum length on initial prompt
            opts.initial_prompt = val[:300]

    return opts
