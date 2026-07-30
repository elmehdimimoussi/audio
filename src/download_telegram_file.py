"""
Telegram file downloader for faster-whisper transcription workflow.

Downloads media files via the Telegram Bot API using stream processing,
strict size limits, timeout handling, and token sanitization.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("download_telegram_file")

DEFAULT_API_BASE_URL = "https://api.telegram.org"
FILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,500}$")


def sanitize_telegram_error(error_msg: str, bot_token: Optional[str] = None) -> str:
    """Strip Telegram bot token and token URLs from exception strings."""
    if not error_msg:
        return "Unknown error"

    sanitized = error_msg
    if bot_token and bot_token in sanitized:
        sanitized = sanitized.replace(bot_token, "[REDACTED_TOKEN]")

    # Redact any bot<token> URL patterns
    sanitized = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED_TOKEN]", sanitized)
    return sanitized


def validate_file_id(file_id: str) -> str:
    """Validate Telegram file_id format and length."""
    if not file_id or not isinstance(file_id, str):
        raise ValueError("Telegram file_id must be a non-empty string.")

    file_id_clean = file_id.strip()
    if not FILE_ID_PATTERN.match(file_id_clean):
        raise ValueError(
            f"Invalid Telegram file_id format or length (length={len(file_id_clean)}). "
            "Must contain only alphanumeric characters, underscores, and hyphens."
        )

    return file_id_clean


def download_telegram_file(
    file_id: str,
    output_path: Path | str,
    bot_token: Optional[str] = None,
    api_base_url: Optional[str] = None,
    max_bytes: int = 2 * 1024 * 1024 * 1024,  # 2 GB max limit
) -> Path:
    """
    Query Telegram getFile API and download media file safely to output_path.

    Args:
        file_id: Telegram media file_id.
        output_path: Target filesystem path.
        bot_token: Telegram bot token (defaults to TELEGRAM_BOT_TOKEN env var).
        api_base_url: Base Telegram API URL (defaults to TELEGRAM_API_BASE_URL env var or official endpoint).
        max_bytes: Maximum allowed size in bytes.

    Returns:
        Path object pointing to downloaded file.
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable or parameter is missing.")

    base_url = (api_base_url or os.getenv("TELEGRAM_API_BASE_URL", DEFAULT_API_BASE_URL)).rstrip("/")
    clean_file_id = validate_file_id(file_id)

    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    get_file_url = f"{base_url}/bot{token}/getFile"

    logger.info(f"Resolving Telegram file metadata for file_id: {clean_file_id[:12]}...")

    try:
        response = requests.get(
            get_file_url,
            params={"file_id": clean_file_id},
            timeout=(10.0, 30.0),
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        safe_msg = sanitize_telegram_error(str(e), token)
        raise RuntimeError(f"Failed to query Telegram getFile API: {safe_msg}") from None

    if not data.get("ok") or "result" not in data:
        description = data.get("description", "Unknown Telegram API error")
        safe_desc = sanitize_telegram_error(description, token)
        raise RuntimeError(f"Telegram getFile API error: {safe_desc}")

    file_result = data["result"]
    telegram_file_path = file_result.get("file_path")
    reported_file_size = file_result.get("file_size", 0)

    if not telegram_file_path:
        raise RuntimeError("Telegram getFile API response did not contain file_path.")

    if reported_file_size > max_bytes:
        raise ValueError(
            f"Reported file size ({reported_file_size} bytes / {reported_file_size / (1024*1024):.2f} MB) "
            f"exceeds limit of {max_bytes} bytes."
        )

    download_url = f"{base_url}/file/bot{token}/{telegram_file_path}"
    logger.info(f"Downloading Telegram media stream to {target_path.name}...")

    downloaded_bytes = 0
    try:
        with requests.get(download_url, stream=True, timeout=(10.0, 300.0)) as resp:
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > max_bytes:
                        raise ValueError(
                            f"Downloaded data exceeded maximum allowed size of {max_bytes} bytes."
                        )
                    f.write(chunk)

    except Exception as e:
        if target_path.exists():
            try:
                target_path.unlink()
                logger.info(f"Cleaned up partial download file: {target_path.name}")
            except Exception as cleanup_err:
                logger.warning(f"Could not remove partial download file: {cleanup_err}")

        safe_msg = sanitize_telegram_error(str(e), token)
        raise RuntimeError(f"Failed to download Telegram media file: {safe_msg}") from None

    if downloaded_bytes == 0:
        if target_path.exists():
            target_path.unlink()
        raise ValueError("Downloaded file is empty (0 bytes).")

    logger.info(
        f"Successfully downloaded Telegram media file: {target_path.name} "
        f"({downloaded_bytes} bytes / {downloaded_bytes / (1024*1024):.2f} MB)"
    )

    return target_path


def main(args: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Secure Telegram file downloader for transcription workflow")
    parser.add_argument("--file-id", type=str, required=True, help="Telegram file_id")
    parser.add_argument("--output-path", type=str, required=True, help="Target local path")
    parser.add_argument("--max-size-mb", type=int, default=2000, help="Max file size in MB")
    parser.add_argument("--api-base-url", type=str, default="", help="Custom Telegram API base URL")

    parsed = parser.parse_args(args)

    max_bytes = parsed.max_size_mb * 1024 * 1024
    api_url = parsed.api_base_url if parsed.api_base_url else None

    try:
        download_telegram_file(
            file_id=parsed.file_id,
            output_path=parsed.output_path,
            api_base_url=api_url,
            max_bytes=max_bytes,
        )
        sys.exit(0)
    except Exception as e:
        logger.error(f"Telegram file download failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
