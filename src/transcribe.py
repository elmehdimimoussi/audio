"""
Main transcription pipeline script using faster-whisper.

Handles URL downloading, audio probing & validation, model loading,
incremental segment processing, signal handling, and transcript export.
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure src modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audio_validator import validate_audio_file
from src.downloader import download_file, sanitize_url_for_logging
from src.subtitle_writer import write_transcripts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("transcribe")

SUPPORTED_MODELS = {"tiny", "base", "small", "medium", "large-v3", "turbo"}
CANCEL_REQUESTED = False


def str2bool(v: Any) -> bool:
    """Parse boolean from string or bool argument."""
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError(f"Boolean value expected, got '{v}'.")


def handle_signals(signum: int, frame: Any) -> None:
    """Graceful signal handler for interruption."""
    global CANCEL_REQUESTED
    sig_name = signal.Signals(signum).name
    logger.warning(f"Received termination signal ({sig_name}). Requesting graceful shutdown...")
    CANCEL_REQUESTED = True


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(
        description="Production Audio/Video Transcriber using faster-whisper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--audio-url", type=str, default="", help="HTTPS URL pointing to audio/video file")
    parser.add_argument("--audio-file", type=str, default="", help="Local path to audio/video file")
    parser.add_argument("--language", type=str, default="ar", help="Language code (e.g. 'ar', 'en', 'fr', 'auto')")
    parser.add_argument("--model", type=str, default="medium", choices=sorted(SUPPORTED_MODELS), help="Whisper model size")
    parser.add_argument("--output-formats", type=str, default="txt", help="Comma-separated list of formats (txt, srt, vtt, json)")
    parser.add_argument("--output-dir", type=str, default="output", help="Directory to save transcript files")
    parser.add_argument("--vad-filter", type=str2bool, default=True, help="Enable Silero VAD filtering")
    parser.add_argument("--word-timestamps", type=str2bool, default=True, help="Enable word-level timestamps")
    parser.add_argument("--initial-prompt", type=str, default="", help="Initial prompt to guide Whisper (names, terminology, etc.)")
    parser.add_argument("--device", type=str, default="cpu", help="Compute device (cpu, cuda)")
    parser.add_argument("--compute-type", type=str, default="int8", help="Quantization / compute type (int8, float32, float16)")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam search size")
    parser.add_argument("--model-cache-dir", type=str, default="", help="Custom model cache directory")
    parser.add_argument("--max-file-size-mb", type=int, default=2000, help="Maximum allowed audio file size in MB")
    parser.add_argument("--max-duration-hours", type=float, default=2.0, help="Maximum allowed media duration in hours")

    parsed = parser.parse_args(args)

    if not parsed.audio_url and not parsed.audio_file:
        parser.error("Either --audio-url or --audio-file must be provided.")

    if parsed.audio_url and parsed.audio_file:
        logger.info("Both --audio-url and --audio-file provided. --audio-url will take precedence.")

    return parsed


def run_transcription(args: argparse.Namespace) -> int:
    """Execute complete transcription pipeline."""
    signal.signal(signal.SIGINT, handle_signals)
    signal.signal(signal.SIGTERM, handle_signals)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    local_audio_path: Path
    source_info: Dict[str, Any] = {}

    try:
        # Step 1: Download or locate media
        if args.audio_url:
            sanitized_url = sanitize_url_for_logging(args.audio_url)
            source_info["url"] = sanitized_url
            max_bytes = args.max_file_size_mb * 1024 * 1024
            logger.info(f"Downloading media file from HTTPS URL: {sanitized_url}")
            local_audio_path = download_file(
                url=args.audio_url,
                output_dir=temp_dir,
                max_bytes=max_bytes,
            )
        else:
            local_audio_path = Path(args.audio_file)
            source_info["file"] = local_audio_path.name
            if not local_audio_path.exists():
                raise FileNotFoundError(f"Specified --audio-file does not exist: {local_audio_path}")

        # Step 2: Validate audio file
        max_duration_sec = args.max_duration_hours * 3600.0
        max_bytes = args.max_file_size_mb * 1024 * 1024
        logger.info(f"Validating media file: {local_audio_path.name}")

        metadata = validate_audio_file(
            file_path=local_audio_path,
            max_duration_seconds=max_duration_sec,
            max_size_bytes=max_bytes,
        )
        source_info.update(metadata.to_dict())

        # Step 3: Lazy-import faster-whisper and load model
        logger.info(f"Loading faster-whisper model '{args.model}' (device={args.device}, compute_type={args.compute_type})...")
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            logger.error("faster-whisper is not installed in the environment.")
            raise RuntimeError("faster-whisper dependency missing. Please install requirements.txt.") from e

        cache_dir = args.model_cache_dir if args.model_cache_dir else None
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=cache_dir,
        )

        # Step 4: Configure language parameters
        requested_lang = args.language.strip().lower()
        whisper_lang = None if requested_lang in ("auto", "", "none") else requested_lang
        logger.info(f"Requested language parameter: '{requested_lang}' (Whisper lang='{whisper_lang}')")

        initial_prompt = args.initial_prompt.strip() if args.initial_prompt else None
        if initial_prompt:
            logger.info(f"Using initial prompt (length={len(initial_prompt)} chars)")

        # Step 5: Execute transcription with incremental streaming
        logger.info("Starting transcription...")
        process_start = time.perf_counter()

        segments_generator, info = model.transcribe(
            str(local_audio_path),
            language=whisper_lang,
            task="transcribe",
            beam_size=args.beam_size,
            vad_filter=args.vad_filter,
            word_timestamps=args.word_timestamps,
            initial_prompt=initial_prompt,
        )

        logger.info(
            f"Model language detection complete: Detected='{info.language}' "
            f"(Probability={info.language_probability:.4f})"
        )

        collected_segments: List[Dict[str, Any]] = []
        segment_count = 0

        for segment in segments_generator:
            if CANCEL_REQUESTED:
                logger.warning("Transcription interrupted by cancellation request. Saving partial progress...")
                break

            seg_data: Dict[str, Any] = {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }

            if args.word_timestamps and hasattr(segment, "words") and segment.words:
                seg_data["words"] = [
                    {
                        "start": w.start,
                        "end": w.end,
                        "word": w.word,
                        "probability": w.probability,
                    }
                    for w in segment.words
                ]

            collected_segments.append(seg_data)
            segment_count += 1

            start_min = int(segment.start // 60)
            start_sec = int(segment.start % 60)
            end_min = int(segment.end // 60)
            end_sec = int(segment.end % 60)

            logger.info(
                f"[{start_min:02d}:{start_sec:02d} -> {end_min:02d}:{end_sec:02d}] "
                f"{segment.text.strip()}"
            )

        process_end = time.perf_counter()
        processing_seconds = process_end - process_start
        rtf = processing_seconds / metadata.duration_seconds if metadata.duration_seconds > 0 else 0.0

        logger.info(
            f"Transcription complete! Processed {len(collected_segments)} segments in "
            f"{processing_seconds:.2f}s (Real-Time Factor: {rtf:.3f}x)"
        )

        # Step 6: Write transcripts to disk
        transcription_metadata = {
            "model": args.model,
            "requested_language": args.language,
            "detected_language": info.language,
            "language_probability": info.language_probability,
            "duration_seconds": metadata.duration_seconds,
            "processing_seconds": processing_seconds,
        }

        requested_formats = [f.strip() for f in args.output_formats.split(",") if f.strip()]
        base_name = "transcript"

        written_files = write_transcripts(
            output_dir=output_dir,
            base_filename=base_name,
            segments=collected_segments,
            requested_formats=requested_formats,
            source_info=source_info,
            transcription_metadata=transcription_metadata,
            include_words=args.word_timestamps,
        )

        logger.info("Successfully generated output artifacts:")
        for fmt, path in written_files.items():
            logger.info(f"  - {fmt.upper()}: {path}")

        # Cleanup temporary downloaded file if present
        if args.audio_url and local_audio_path.exists():
            try:
                local_audio_path.unlink()
                logger.info(f"Cleaned up temporary audio file: {local_audio_path.name}")
            except Exception as e:
                logger.warning(f"Could not remove temp file {local_audio_path}: {e}")

        return 0

    except Exception as e:
        logger.error(f"Transcription pipeline failed: {e}", exc_info=True)
        return 1


def main() -> None:
    args = parse_args()
    sys.exit(run_transcription(args))


if __name__ == "__main__":
    main()
