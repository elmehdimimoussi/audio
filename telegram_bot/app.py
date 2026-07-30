"""
FastAPI Telegram Webhook Service for faster-whisper GitHub Actions workflow dispatch.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from telegram_bot.config import get_settings
from telegram_bot.github_client import GitHubDispatchClient
from telegram_bot.media import extract_media_info, parse_caption_options
from telegram_bot.state import StateManager
from telegram_bot.telegram_client import TelegramClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_bot_app")

settings = get_settings()
state_mgr = StateManager(db_path=settings.BOT_STATE_DB_PATH)
github_client = GitHubDispatchClient(settings)
telegram_client = TelegramClient(settings)

app = FastAPI(
    title="Telegram Whisper Bot Service",
    description="Webhook listener for dispatching faster-whisper transcription workflows to GitHub Actions",
    version="1.0.0",
)


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint. Exposes no secrets or internal configuration."""
    return {"status": "ok", "service": "telegram-whisper-bot"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> Response:
    """
    Telegram webhook endpoint.
    Verifies secret header, authorizes user, validates media format,
    sends immediate Telegram response, and dispatches GitHub Actions workflow.
    """
    # 1. Verify Telegram Webhook Secret Header if configured
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET.strip()
    if expected_secret:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != expected_secret:
            logger.warning("Rejected webhook request: missing or invalid X-Telegram-Bot-Api-Secret-Token header.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing webhook secret token.",
            )

    try:
        update_data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON payload: {e}")
        return JSONResponse(status_code=200, content={"status": "invalid_json_ignored"})

    update_id = update_data.get("update_id")
    if not update_id:
        return JSONResponse(status_code=200, content={"status": "no_update_id_ignored"})

    # 2. Idempotency Check: Ignore duplicate update_id
    existing_req = state_mgr.get_by_update_id(update_id)
    if existing_req:
        logger.info(f"Duplicate Telegram update_id={update_id} received. Skipping duplicate processing.")
        return JSONResponse(status_code=200, content={"status": "duplicate_update_ignored"})

    message = update_data.get("message") or update_data.get("edited_message")
    if not message:
        return JSONResponse(status_code=200, content={"status": "non_message_update_ignored"})

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    text = (message.get("text") or "").strip()

    user_id = from_user.get("id")
    chat_id = chat.get("id")
    chat_type = (chat.get("type") or "private").lower()

    if not user_id or not chat_id:
        return JSONResponse(status_code=200, content={"status": "missing_ids_ignored"})

    # 3. Check Chat Type Authorization
    allowed_types = settings.allowed_chat_types_list
    if chat_type not in allowed_types:
        logger.info(f"Rejected message from unauthorized chat type '{chat_type}' (chat_id={chat_id}).")
        return JSONResponse(status_code=200, content={"status": "chat_type_not_allowed"})

    # 4. Check Telegram User Authorization
    allowed_users = settings.allowed_user_ids
    if allowed_users and user_id not in allowed_users:
        logger.warning(f"Unauthorized access attempt by user_id={user_id} in chat_id={chat_id}.")
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ Sorry, you are not authorized to use this transcription bot.",
        )
        return JSONResponse(status_code=200, content={"status": "user_unauthorized"})

    # 5. Handle Bot Commands (/start, /help, /status, /url)
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            help_text = (
                "🎙️ <b>faster-whisper Transcription Bot</b>\n\n"
                "Send me an audio, voice message, video, or supported document to transcribe!\n\n"
                "<b>Supported Formats:</b> MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, MP4, MOV, MKV, WEBM\n"
                "<b>Duration Limit:</b> Up to 2 hours\n"
                "<b>Direct Upload Limit:</b> Up to 20 MB\n\n"
                "<b>Large File Support:</b>\n"
                "For files over 20 MB, send an HTTPS download link using:\n"
                "<code>/url https://example.com/audio.mp3</code>\n\n"
                "<b>Caption Options:</b>\n"
                "Add key=value options in your message caption:\n"
                "<code>language=ar</code>\n"
                "<code>model=medium</code> (tiny, base, small, medium, large-v3, turbo)\n"
                "<code>formats=txt</code>\n"
                "<code>prompt=Vocabulary terms</code>"
            )
            await telegram_client.send_message(chat_id=chat_id, text=help_text, parse_mode="HTML")
            return JSONResponse(status_code=200, content={"status": "command_handled"})

        elif cmd == "/status":
            if not args:
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text="Usage: <code>/status &lt;request_id&gt;</code>",
                    parse_mode="HTML",
                )
                return JSONResponse(status_code=200, content={"status": "command_handled"})

            rec = state_mgr.get_by_request_id(args)
            if not rec:
                await telegram_client.send_message(chat_id=chat_id, text="Request ID not found.")
            else:
                msg = (
                    f"📋 <b>Request Status</b>\n\n"
                    f"• <b>Request ID:</b> <code>{rec['request_id'][:13]}</code>\n"
                    f"• <b>Status:</b> <code>{rec['status']}</code>\n"
                    f"• <b>Workflow Run ID:</b> <code>{rec['workflow_run_id'] or 'N/A'}</code>"
                )
                await telegram_client.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
            return JSONResponse(status_code=200, content={"status": "command_handled"})

        elif cmd == "/url":
            if not args or not args.lower().startswith("https://"):
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text="⚠️ Please provide a valid direct <code>https://</code> URL.\nExample: <code>/url https://example.com/media.mp3</code>",
                    parse_mode="HTML",
                )
                return JSONResponse(status_code=200, content={"status": "command_handled"})

            # Check rate limit
            if state_mgr.has_active_request_for_user(user_id):
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text="⏳ You already have an active transcription request in progress. Please wait for it to finish.",
                )
                return JSONResponse(status_code=200, content={"status": "rate_limited"})

            req_id = str(uuid.uuid4())
            opts = parse_caption_options(
                caption="",
                default_lang=settings.DEFAULT_LANGUAGE,
                default_model=settings.DEFAULT_MODEL,
            )

            status_text = (
                "✅ <b>Transcription request received (URL Mode).</b>\n\n"
                f"• <b>Request ID:</b> <code>{req_id[:13]}</code>\n"
                f"• <b>Language:</b> <code>{opts.language}</code>\n"
                f"• <b>Model:</b> <code>{opts.model}</code>\n"
                "• <b>Status:</b> <code>queued</code>"
            )
            success, smid, err = await telegram_client.send_message(
                chat_id=chat_id, text=status_text, parse_mode="HTML", reply_to_message_id=message.get("message_id")
            )

            state_mgr.create_request(
                request_id=req_id,
                update_id=update_id,
                user_id=user_id,
                chat_id=chat_id,
                status_message_id=smid,
                file_id=None,
                status="queued",
            )

            wf_inputs = {
                "source_type": "url",
                "audio_url": args,
                "request_id": req_id,
                "language": opts.language,
                "model": opts.model,
                "output_formats": opts.output_formats,
                "vad_filter": opts.vad_filter,
                "word_timestamps": opts.word_timestamps,
                "initial_prompt": opts.initial_prompt,
            }

            dispatch_ok, dispatch_msg = await github_client.trigger_workflow(wf_inputs)
            if dispatch_ok:
                state_mgr.update_request_status(req_id, status="queued")
            else:
                state_mgr.update_request_status(req_id, status="failed")
                if smid:
                    await telegram_client.edit_message(
                        chat_id=chat_id,
                        message_id=smid,
                        text=f"❌ <b>GitHub Dispatch Failed</b>\n\n{dispatch_msg}",
                        parse_mode="HTML",
                    )
            return JSONResponse(status_code=200, content={"status": "url_dispatched"})

    # 6. Extract Media Attachment
    media_info, err_msg = extract_media_info(update_data)
    if not media_info:
        logger.info(f"Ignored non-media message from user_id={user_id}: {err_msg}")
        return JSONResponse(status_code=200, content={"status": "no_valid_media_ignored"})

    # 7. Enforce Direct Download Size Limit
    if media_info.file_size > settings.TELEGRAM_MAX_DIRECT_DOWNLOAD_BYTES:
        max_mb = settings.TELEGRAM_MAX_DIRECT_DOWNLOAD_BYTES / (1024 * 1024)
        file_mb = media_info.file_size / (1024 * 1024)
        msg = (
            f"⚠️ <b>File Exceeds Direct Download Limit</b>\n\n"
            f"Your media file is {file_mb:.1f} MB, which exceeds Telegram's direct upload limit of {max_mb:.0f} MB.\n\n"
            "Please upload your file to temporary HTTPS storage and send the link using:\n"
            "<code>/url https://example.com/your-media-link</code>"
        )
        await telegram_client.send_message(chat_id=chat_id, text=msg, parse_mode="HTML", reply_to_message_id=media_info.message_id)
        return JSONResponse(status_code=200, content={"status": "file_oversized_notified"})

    # 8. Check Per-User Rate Limit (Single active transcription)
    if state_mgr.has_active_request_for_user(user_id):
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⏳ You already have an active transcription request in progress. Please wait for it to complete.",
            reply_to_message_id=media_info.message_id,
        )
        return JSONResponse(status_code=200, content={"status": "rate_limited"})

    # 9. Create Request and Immediate Response
    req_id = str(uuid.uuid4())
    opts = parse_caption_options(
        caption=media_info.caption,
        default_lang=settings.DEFAULT_LANGUAGE,
        default_model=settings.DEFAULT_MODEL,
    )

    status_text = (
        "✅ <b>Transcription request received.</b>\n\n"
        f"• <b>Request ID:</b> <code>{req_id[:13]}</code>\n"
        f"• <b>Language:</b> <code>{opts.language}</code>\n"
        f"• <b>Model:</b> <code>{opts.model}</code>\n"
        "• <b>Status:</b> <code>queued</code>"
    )

    success, smid, err = await telegram_client.send_message(
        chat_id=chat_id,
        text=status_text,
        parse_mode="HTML",
        reply_to_message_id=media_info.message_id,
    )

    state_mgr.create_request(
        request_id=req_id,
        update_id=update_id,
        user_id=user_id,
        chat_id=chat_id,
        status_message_id=smid,
        file_id=media_info.file_id,
        status="queued",
    )

    # 10. Dispatch GitHub Actions Workflow
    wf_inputs = {
        "source_type": "telegram",
        "telegram_file_id": media_info.file_id,
        "telegram_chat_id": str(chat_id),
        "telegram_status_message_id": str(smid) if smid else "",
        "request_id": req_id,
        "language": opts.language,
        "model": opts.model,
        "output_formats": opts.output_formats,
        "vad_filter": opts.vad_filter,
        "word_timestamps": opts.word_timestamps,
        "initial_prompt": opts.initial_prompt,
    }

    dispatch_ok, dispatch_msg = await github_client.trigger_workflow(wf_inputs)

    if dispatch_ok:
        state_mgr.update_request_status(req_id, status="queued")
    else:
        state_mgr.update_request_status(req_id, status="failed")
        if smid:
            await telegram_client.edit_message(
                chat_id=chat_id,
                message_id=smid,
                text=f"❌ <b>GitHub Workflow Dispatch Failed</b>\n\n{dispatch_msg}",
                parse_mode="HTML",
            )

    return JSONResponse(status_code=200, content={"status": "request_dispatched"})
