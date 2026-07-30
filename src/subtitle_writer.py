"""
Subtitle and transcript writer module supporting TXT, SRT, VTT, and JSON formats.

Ensures strict compliance with subtitle specifications, correct timestamp formatting,
UTF-8 Arabic text encoding without manual text reshaping, and non-negative timestamp validation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def format_timestamp_srt(seconds: float) -> str:
    """
    Format time in seconds to SRT timestamp string (HH:MM:SS,mmm).
    """
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
        if secs >= 60:
            minutes += 1
            secs -= 60
            if minutes >= 60:
                hours += 1
                minutes -= 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """
    Format time in seconds to WebVTT timestamp string (HH:MM:SS.mmm).
    """
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
        if secs >= 60:
            minutes += 1
            secs -= 60
            if minutes >= 60:
                hours += 1
                minutes -= 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def generate_txt(segments: List[Dict[str, Any]]) -> str:
    """
    Generate clean plain text transcript separated by segment boundaries.
    """
    paragraphs = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs) + "\n" if paragraphs else ""


def generate_srt(segments: List[Dict[str, Any]]) -> str:
    """
    Generate valid SRT formatted subtitles.
    Sequential numbering from 1.
    Timestamps in HH:MM:SS,mmm format.
    """
    entries = []
    sub_index = 1

    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue

        start = max(0.0, float(segment.get("start", 0.0)))
        end = max(start, float(segment.get("end", 0.0)))

        start_str = format_timestamp_srt(start)
        end_str = format_timestamp_srt(end)

        entry = f"{sub_index}\n{start_str} --> {end_str}\n{text}\n"
        entries.append(entry)
        sub_index += 1

    return "\n".join(entries) + "\n" if entries else ""


def generate_vtt(segments: List[Dict[str, Any]]) -> str:
    """
    Generate valid WebVTT formatted subtitles starting with WEBVTT header.
    Timestamps in HH:MM:SS.mmm format.
    """
    lines = ["WEBVTT\n"]

    for sub_index, segment in enumerate(segments, start=1):
        text = segment.get("text", "").strip()
        if not text:
            continue

        start = max(0.0, float(segment.get("start", 0.0)))
        end = max(start, float(segment.get("end", 0.0)))

        start_str = format_timestamp_vtt(start)
        end_str = format_timestamp_vtt(end)

        lines.append(f"{sub_index}\n{start_str} --> {end_str}\n{text}\n")

    return "\n".join(lines)


def generate_json(
    source_info: Dict[str, Any],
    transcription_metadata: Dict[str, Any],
    segments: List[Dict[str, Any]],
    include_words: bool = True,
) -> str:
    """
    Generate structured JSON representation of the transcription.
    """
    cleaned_segments = []
    for idx, seg in enumerate(segments):
        cleaned_seg = {
            "id": idx,
            "start": round(max(0.0, float(seg.get("start", 0.0))), 3),
            "end": round(max(float(seg.get("start", 0.0)), float(seg.get("end", 0.0))), 3),
            "text": seg.get("text", "").strip(),
        }

        if include_words and "words" in seg and seg["words"]:
            words_list = []
            for w in seg["words"]:
                words_list.append({
                    "start": round(max(0.0, float(w.get("start", 0.0))), 3),
                    "end": round(max(float(w.get("start", 0.0)), float(w.get("end", 0.0))), 3),
                    "word": w.get("word", ""),
                    "probability": round(float(w.get("probability", 1.0)), 4),
                })
            cleaned_seg["words"] = words_list

        cleaned_segments.append(cleaned_seg)

    payload = {
        "source": source_info,
        "transcription": {
            "model": transcription_metadata.get("model", ""),
            "requested_language": transcription_metadata.get("requested_language", ""),
            "detected_language": transcription_metadata.get("detected_language", ""),
            "language_probability": round(float(transcription_metadata.get("language_probability", 0.0)), 4),
            "duration_seconds": round(float(transcription_metadata.get("duration_seconds", 0.0)), 3),
            "processing_seconds": round(float(transcription_metadata.get("processing_seconds", 0.0)), 3),
            "segments": cleaned_segments,
        },
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_transcripts(
    output_dir: Path | str,
    base_filename: str,
    segments: List[Dict[str, Any]],
    requested_formats: List[str],
    source_info: Optional[Dict[str, Any]] = None,
    transcription_metadata: Optional[Dict[str, Any]] = None,
    include_words: bool = True,
) -> Dict[str, Path]:
    """
    Write generated subtitle/transcript files in the specified formats.

    Returns:
        Dictionary mapping format name to output file Path.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    source_info = source_info or {}
    transcription_metadata = transcription_metadata or {}

    written_files: Dict[str, Path] = {}
    normalized_formats = [fmt.strip().lower() for fmt in requested_formats]

    for fmt in set(normalized_formats):
        if fmt == "txt":
            content = generate_txt(segments)
            file_path = out_dir / f"{base_filename}.txt"
            file_path.write_text(content, encoding="utf-8")
            written_files["txt"] = file_path
            logger.info(f"Wrote TXT transcript to {file_path}")

        elif fmt == "srt":
            content = generate_srt(segments)
            file_path = out_dir / f"{base_filename}.srt"
            file_path.write_text(content, encoding="utf-8")
            written_files["srt"] = file_path
            logger.info(f"Wrote SRT subtitles to {file_path}")

        elif fmt == "vtt":
            content = generate_vtt(segments)
            file_path = out_dir / f"{base_filename}.vtt"
            file_path.write_text(content, encoding="utf-8")
            written_files["vtt"] = file_path
            logger.info(f"Wrote VTT subtitles to {file_path}")

        elif fmt == "json":
            content = generate_json(source_info, transcription_metadata, segments, include_words=include_words)
            file_path = out_dir / f"{base_filename}.json"
            file_path.write_text(content, encoding="utf-8")
            written_files["json"] = file_path
            logger.info(f"Wrote JSON transcript to {file_path}")

        else:
            logger.warning(f"Unsupported output format requested: '{fmt}'")

    return written_files
