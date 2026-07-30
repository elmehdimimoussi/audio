"""
Audio file validation module using ffprobe.

Validates file existence, non-emptiness, presence of audio streams,
container/codec decoding, file size limits, and duration constraints.
"""

import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AudioMetadata:
    """Structured metadata extracted from audio/video media."""
    duration_seconds: float
    duration_formatted: str
    file_size_bytes: int
    container_format: str
    audio_codec: str
    sample_rate: int
    channels: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to HH:MM:SS string."""
    total_seconds = max(0, int(round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def run_ffprobe(file_path: Path) -> Dict[str, Any]:
    """Execute ffprobe and return parsed JSON stdout."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,format_name,size,bit_rate:stream=index,codec_type,codec_name,sample_rate,channels",
        "-of", "json",
        str(file_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as e:
        raise RuntimeError("ffprobe is not installed or not found in PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("ffprobe process timed out while probing the media file.") from e

    if result.returncode != 0:
        stderr_msg = result.stderr.strip() if result.stderr else "Unknown error"
        raise ValueError(f"ffprobe failed to decode media file: {stderr_msg}")

    try:
        data = json.loads(result.stdout)
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse ffprobe JSON output: {e}") from e


def validate_audio_file(
    file_path: Path | str,
    max_duration_seconds: float = 7200.0,  # 2 hours
    tolerance_seconds: float = 60.0,       # 1 minute tolerance
    max_size_bytes: int = 2 * 1024 * 1024 * 1024,  # 2 GB
) -> AudioMetadata:
    """
    Validate downloaded media file using ffprobe.

    Args:
        file_path: Path to the audio/video file.
        max_duration_seconds: Maximum allowed duration (default 2 hours = 7200s).
        tolerance_seconds: Grace period added to max_duration_seconds.
        max_size_bytes: Maximum allowed file size in bytes.

    Returns:
        AudioMetadata object containing extracted stream and format properties.

    Raises:
        ValueError: If any validation rule is violated.
        FileNotFoundError: If file path does not exist.
        RuntimeError: If ffprobe command execution fails.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Media file does not exist: {path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Media file is empty (0 bytes): {path}")

    if file_size > max_size_bytes:
        raise ValueError(
            f"Media file size ({file_size} bytes / {file_size / (1024*1024):.2f} MB) "
            f"exceeds maximum allowed limit of {max_size_bytes} bytes."
        )

    prob_data = run_ffprobe(path)

    streams = prob_data.get("streams", [])
    format_info = prob_data.get("format", {})

    audio_stream: Optional[Dict[str, Any]] = None
    for stream in streams:
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break

    if not audio_stream:
        raise ValueError("Media file contains no audio stream suitable for transcription.")

    # Determine duration from format or audio stream
    raw_duration = format_info.get("duration") or audio_stream.get("duration")
    if raw_duration is None:
        raise ValueError("Could not determine audio duration from ffprobe metadata.")

    try:
        duration = float(raw_duration)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid duration value '{raw_duration}': {e}") from e

    if duration <= 0:
        raise ValueError(f"Media duration must be greater than zero. Got {duration} seconds.")

    allowed_max_duration = max_duration_seconds + tolerance_seconds
    if duration > allowed_max_duration:
        formatted_curr = format_duration(duration)
        formatted_max = format_duration(max_duration_seconds)
        raise ValueError(
            f"Media duration ({formatted_curr}) exceeds maximum allowed limit of {formatted_max} "
            f"(allowing up to {tolerance_seconds}s tolerance)."
        )

    container_format = format_info.get("format_name", "unknown")
    audio_codec = audio_stream.get("codec_name", "unknown")

    sample_rate = 0
    if "sample_rate" in audio_stream:
        try:
            sample_rate = int(audio_stream["sample_rate"])
        except ValueError:
            pass

    channels = 0
    if "channels" in audio_stream:
        try:
            channels = int(audio_stream["channels"])
        except ValueError:
            pass

    metadata = AudioMetadata(
        duration_seconds=round(duration, 3),
        duration_formatted=format_duration(duration),
        file_size_bytes=file_size,
        container_format=container_format,
        audio_codec=audio_codec,
        sample_rate=sample_rate,
        channels=channels,
    )

    logger.info(
        f"Media validation passed: Duration={metadata.duration_formatted} ({metadata.duration_seconds}s), "
        f"Codec={metadata.audio_codec}, Container={metadata.container_format}, "
        f"Sample Rate={metadata.sample_rate}Hz, Channels={metadata.channels}"
    )

    return metadata
