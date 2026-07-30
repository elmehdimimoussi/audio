"""
Safe HTTPS media downloader module.

Enforces HTTPS, streaming downloads, file size limits, redirect limits,
and sanitized logging without exposing credentials or query parameters.
"""

import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    ".opus", ".mp4", ".mov", ".mkv", ".webm"
}

CONTENT_TYPE_MAP = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "audio/webm": ".webm",
}


def sanitize_url_for_logging(url: str) -> str:
    """
    Remove credentials and query parameters from URL for safe logging.
    """
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        # Strip userinfo (username:password)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        
        # Redact query params
        sanitized_query = ""
        if parsed.query:
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            sanitized_pairs = [(k, "***") for k, _ in query_pairs]
            sanitized_query = urllib.parse.urlencode(sanitized_pairs, safe="*")
            
        sanitized_url = urllib.parse.urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            sanitized_query,
            ""  # strip fragment
        ))
        return sanitized_url
    except Exception:
        return "[REDACTED_URL]"


def determine_file_extension(url: str, content_type: Optional[str] = None) -> str:
    """
    Determine safe file extension from Content-Type or URL path.
    """
    if content_type:
        clean_ct = content_type.split(";")[0].strip().lower()
        if clean_ct in CONTENT_TYPE_MAP:
            return CONTENT_TYPE_MAP[clean_ct]

    parsed = urllib.parse.urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in ALLOWED_EXTENSIONS:
        return ext

    return ".media"


def download_file(
    url: str,
    output_dir: Path | str,
    max_bytes: int = 2 * 1024 * 1024 * 1024,  # 2 GB default
    connect_timeout: float = 10.0,
    read_timeout: float = 30.0,
    max_redirects: int = 5,
) -> Path:
    """
    Download a file from an HTTPS URL safely.

    Args:
        url: The HTTPS URL to download from.
        output_dir: Directory to save the downloaded file.
        max_bytes: Maximum allowed file size in bytes.
        connect_timeout: HTTP connect timeout in seconds.
        read_timeout: HTTP read timeout in seconds per chunk.
        max_redirects: Maximum number of HTTP redirects allowed.

    Returns:
        Path to the downloaded media file.

    Raises:
        ValueError: If URL is invalid, non-HTTPS, or exceeds constraints.
        RuntimeError: If download fails or exceeds max_bytes.
    """
    if not url or not url.strip():
        raise ValueError("Audio URL must not be empty.")

    url = url.strip()
    parsed_url = urllib.parse.urlparse(url)

    if parsed_url.scheme.lower() != "https":
        raise ValueError(f"Security error: Only HTTPS URLs are allowed. Got scheme '{parsed_url.scheme}'.")

    sanitized_log_url = sanitize_url_for_logging(url)
    logger.info(f"Initiating safe download from URL: {sanitized_log_url}")

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "WhisperTranscriber/1.0 (+https://github.com/transcribe-workflow)",
        "Accept": "*/*",
    }

    try:
        import requests
    except ImportError as e:
        raise RuntimeError("The 'requests' package is required for downloading files. Please install requirements.txt.") from e

    session = requests.Session()
    session.max_redirects = max_redirects

    current_url = url
    redirect_count = 0

    try:
        response = session.get(
            current_url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(connect_timeout, read_timeout),
        )

        # Inspect redirect history for security checks
        if len(response.history) > max_redirects:
            raise ValueError(f"Exceeded maximum allowed redirects ({max_redirects}).")

        for res in response.history:
            res_parsed = urllib.parse.urlparse(res.url)
            if res_parsed.scheme.lower() != "https":
                raise ValueError(f"Redirect security error: non-HTTPS redirect to {res_parsed.scheme} detected.")

        response.raise_for_status()

        content_length_hdr = response.headers.get("Content-Length")
        if content_length_hdr:
            try:
                content_length = int(content_length_hdr)
                if content_length > max_bytes:
                    raise ValueError(
                        f"Content-Length ({content_length} bytes) exceeds max allowed size ({max_bytes} bytes)."
                    )
            except ValueError as ve:
                if "exceeds max allowed size" in str(ve):
                    raise

        ext = determine_file_extension(url, response.headers.get("Content-Type"))
        local_filename = f"input_media{ext}"
        local_path = output_dir_path / local_filename

        downloaded_bytes = 0
        chunk_size = 64 * 1024  # 64 KB chunks

        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > max_bytes:
                        # Clean up partial file
                        f.close()
                        if local_path.exists():
                            local_path.unlink()
                        raise RuntimeError(
                            f"Download aborted: file size exceeded maximum allowed limit of {max_bytes} bytes."
                        )
                    f.write(chunk)

        if downloaded_bytes == 0:
            if local_path.exists():
                local_path.unlink()
            raise RuntimeError("Downloaded file is empty (0 bytes).")

        logger.info(
            f"Successfully downloaded file: {local_path.name} | Size: {downloaded_bytes} bytes ({downloaded_bytes / (1024*1024):.2f} MB)"
        )
        return local_path

    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP request failed for URL {sanitized_log_url}: {e}")
        raise RuntimeError(f"Failed to download file from URL: {e}") from e
