"""
Telegram Notifier module for faster-whisper transcription workflow.

Provides functions and CLI commands to edit Telegram status messages,
upload transcription output files (TXT, SRT, VTT, JSON), and send sanitized
failure notifications to Telegram chats.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_notifier")

DEFAULT_API_BASE_URL = "https://api.telegram.org"


def sanitize_telegram_error(error_msg: str, bot_token: Optional[str] = None) -> str:
    """Sanitize Telegram error messages by stripping tokens and token URLs."""
    if not error_msg:
        return "Unknown error"

    sanitized = str(error_msg)
    if bot_token and bot_token in sanitized:
        sanitized = sanitized.replace(bot_token, "[REDACTED_TOKEN]")

    sanitized = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED_TOKEN]", sanitized)
    return sanitized


def validate_chat_id(chat_id: Union[int, str]) -> int:
    """Validate and convert chat_id to signed integer."""
    try:
        val = int(str(chat_id).strip())
        return val
    except (ValueError, TypeError):
        raise ValueError(f"Invalid Telegram chat_id '{chat_id}'. Must be a signed decimal integer.")


def validate_message_id(message_id: Optional[Union[int, str]]) -> Optional[int]:
    """Validate and convert optional message_id to positive integer."""
    if message_id is None or str(message_id).strip() == "":
        return None
    try:
        val = int(str(message_id).strip())
        if val <= 0:
            raise ValueError()
        return val
    except (ValueError, TypeError):
        raise ValueError(f"Invalid Telegram message_id '{message_id}'. Must be a positive integer.")


class TelegramNotifier:
    """Synchronous HTTP client for sending Telegram status updates and output documents."""

    def __init__(self, bot_token: Optional[str] = None, api_base_url: Optional[str] = None):
        self.token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable or parameter is missing.")

        base_url = api_base_url or os.getenv("TELEGRAM_API_BASE_URL", DEFAULT_API_BASE_URL)
        self.base_url = base_url.rstrip("/")

    def _post(self, method: str, data: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send POST request to Telegram Bot API with sanitization and safe retries."""
        url = f"{self.base_url}/bot{self.token}/{method}"

        max_retries = 3
        backoff = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, data=data, files=files, timeout=(10.0, 60.0))

                # Do not retry 4xx errors (client errors)
                if 400 <= response.status_code < 500:
                    try:
                        res_json = response.json()
                        desc = res_json.get("description", response.text)
                    except Exception:
                        desc = response.text
                    safe_desc = sanitize_telegram_error(desc, self.token)
                    raise RuntimeError(f"Telegram API 4xx error ({response.status_code}): {safe_desc}")

                response.raise_for_status()
                res_json = response.json()

                if not res_json.get("ok"):
                    desc = res_json.get("description", "Unknown Telegram API error")
                    safe_desc = sanitize_telegram_error(desc, self.token)
                    raise RuntimeError(f"Telegram API error: {safe_desc}")

                return res_json

            except RuntimeError as e:
                # Re-raise explicit permanent errors (4xx or API failure)
                raise e
            except Exception as e:
                safe_err = sanitize_telegram_error(str(e), self.token)
                if attempt == max_retries:
                    raise RuntimeError(f"Telegram network request failed after {max_retries} attempts: {safe_err}") from None

                logger.warning(f"Telegram request retry {attempt}/{max_retries} due to transient error: {safe_err}")
                time.sleep(backoff)
                backoff *= 2.0

        raise RuntimeError("Failed to complete Telegram POST request.")

    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: Optional[str] = None,
        reply_to_message_id: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        """Send plain text or formatted message to Telegram chat."""
        cid = validate_chat_id(chat_id)
        mid = validate_message_id(reply_to_message_id)

        payload: Dict[str, Any] = {
            "chat_id": cid,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if mid:
            payload["reply_to_message_id"] = mid

        return self._post("sendMessage", data=payload)

    def edit_message(
        self,
        chat_id: Union[int, str],
        message_id: Union[int, str],
        text: str,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Edit existing status message in Telegram chat."""
        cid = validate_chat_id(chat_id)
        mid = validate_message_id(message_id)
        if not mid:
            raise ValueError("message_id is required for edit_message.")

        payload: Dict[str, Any] = {
            "chat_id": cid,
            "message_id": mid,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            return self._post("editMessageText", data=payload)
        except Exception as e:
            # If message was not modified, log warning instead of breaking workflow
            if "message is not modified" in str(e).lower():
                logger.warning("Telegram status message was not modified (content identical).")
                return {"ok": True, "result": {}}
            raise

    def send_document(
        self,
        chat_id: Union[int, str],
        document_path: Path | str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        """Send output document file to Telegram chat."""
        cid = validate_chat_id(chat_id)
        mid = validate_message_id(reply_to_message_id)
        doc_path = Path(document_path)

        if not doc_path.exists():
            raise FileNotFoundError(f"Document file does not exist: {doc_path}")

        payload: Dict[str, Any] = {
            "chat_id": cid,
        }
        if caption:
            payload["caption"] = caption
        if mid:
            payload["reply_to_message_id"] = mid

        with open(doc_path, "rb") as f:
            files = {"document": (doc_path.name, f)}
            return self._post("sendDocument", data=payload, files=files)

    def send_transcription_outputs(
        self,
        chat_id: Union[int, str],
        output_dir: Path | str,
        status_message_id: Optional[Union[int, str]] = None,
    ) -> int:
        """
        Upload all output documents (TXT, SRT, VTT, JSON) from output_dir to Telegram chat.
        Updates status message to completed.
        """
        cid = validate_chat_id(chat_id)
        smid = validate_message_id(status_message_id)
        out_dir = Path(output_dir)

        sent_count = 0
        transcript_json = out_dir / "transcript.json"
        meta_info: Dict[str, Any] = {}
        if transcript_json.exists():
            try:
                data = json.loads(transcript_json.read_text(encoding="utf-8"))
                meta_info = data.get("transcription", {})
            except Exception as e:
                logger.warning(f"Could not read metadata from transcript.json: {e}")

        # Standard supported extensions
        extensions = [".txt", ".srt", ".vtt", ".json"]
        found_files = []
        for ext in extensions:
            fpath = out_dir / f"transcript{ext}"
            if fpath.exists() and fpath.stat().st_size > 0:
                found_files.append(fpath)

        if not found_files:
            logger.warning(f"No non-empty output files found in {out_dir}")

        for fpath in found_files:
            caption = f"📄 {fpath.name.upper()} transcript output"
            logger.info(f"Sending document {fpath.name} to chat_id={cid}...")
            self.send_document(chat_id=cid, document_path=fpath, caption=caption, reply_to_message_id=smid)
            sent_count += 1

        # Update final status message
        if smid:
            dur = meta_info.get("duration_seconds", 0)
            proc = meta_info.get("processing_seconds", 0)
            lang = meta_info.get("detected_language", "unknown")
            model = meta_info.get("model", "whisper")

            mins = int(dur // 60)
            secs = int(dur % 60)

            status_text = (
                "✅ <b>Transcription completed!</b>\n\n"
                f"• <b>Detected Language:</b> <code>{lang}</code>\n"
                f"• <b>Model:</b> <code>{model}</code>\n"
                f"• <b>Audio Duration:</b> {mins:02d}:{secs:02d}\n"
                f"• <b>Processing Time:</b> {proc:.1f}s\n\n"
                "Result files (TXT/SRT) have been attached above."
            )
            try:
                self.edit_message(chat_id=cid, message_id=smid, text=status_text, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Could not update status message to completed: {e}")

        return sent_count

    def send_failure_notification(
        self,
        chat_id: Union[int, str],
        request_id: Optional[str] = None,
        stage: Optional[str] = None,
        status_message_id: Optional[Union[int, str]] = None,
    ) -> None:
        """Send sanitized failure notification to Telegram chat."""
        cid = validate_chat_id(chat_id)
        smid = validate_message_id(status_message_id)

        req_str = request_id[:13] if request_id else "unknown"
        stage_str = stage or "pipeline execution"

        text = (
            "❌ <b>Transcription Failed</b>\n\n"
            f"• <b>Request ID:</b> <code>{req_str}</code>\n"
            f"• <b>Failed Stage:</b> <code>{stage_str}</code>\n\n"
            "An error occurred during transcription processing. "
            "Please check your input audio file format and try again."
        )

        if smid:
            try:
                self.edit_message(chat_id=cid, message_id=smid, text=text, parse_mode="HTML")
                return
            except Exception as e:
                logger.warning(f"Could not edit status message on failure: {e}")

        self.send_message(chat_id=cid, text=text, parse_mode="HTML")


def main(args: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Telegram Notifier CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # edit-status
    p_status = subparsers.add_parser("edit-status", help="Edit status message")
    p_status.add_argument("--chat-id", type=str, required=True)
    p_status.add_argument("--message-id", type=str, required=True)
    p_status.add_argument("--text", type=str, required=True)

    # send-results
    p_results = subparsers.add_parser("send-results", help="Send transcription output files")
    p_results.add_argument("--chat-id", type=str, required=True)
    p_results.add_argument("--output-dir", type=str, required=True)
    p_results.add_argument("--status-message-id", type=str, default="")

    # send-failure
    p_fail = subparsers.add_parser("send-failure", help="Send failure notification")
    p_fail.add_argument("--chat-id", type=str, required=True)
    p_fail.add_argument("--request-id", type=str, default="")
    p_fail.add_argument("--stage", type=str, default="pipeline")
    p_fail.add_argument("--status-message-id", type=str, default="")

    parsed = parser.parse_args(args)

    try:
        notifier = TelegramNotifier()

        if parsed.command == "edit-status":
            notifier.edit_message(
                chat_id=parsed.chat_id,
                message_id=parsed.message_id,
                text=parsed.text,
                parse_mode="HTML",
            )

        elif parsed.command == "send-results":
            notifier.send_transcription_outputs(
                chat_id=parsed.chat_id,
                output_dir=parsed.output_dir,
                status_message_id=parsed.status_message_id if parsed.status_message_id else None,
            )

        elif parsed.command == "send-failure":
            notifier.send_failure_notification(
                chat_id=parsed.chat_id,
                request_id=parsed.request_id if parsed.request_id else None,
                stage=parsed.stage if parsed.stage else None,
                status_message_id=parsed.status_message_id if parsed.status_message_id else None,
            )

        sys.exit(0)

    except Exception as e:
        logger.error(f"Telegram notifier failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
