# GitHub Actions Audio & Video Transcriber (`faster-whisper`) with Telegram Bot Integration

Production-ready GitHub Actions workflow and Python backend tool suite to transcribe audio and video files locally using `faster-whisper` on a CPU-hosted GitHub Actions runner. Supports both manual HTTPS URL triggers and interactive Telegram bot integration. **No OpenAI API key required.**

---

## 📐 System Architecture

```text
Telegram User
    │
    │ sends audio, voice, video, or media document
    ▼
Telegram Bot Webhook Service (FastAPI / Docker)
    │
    │ GitHub REST API workflow_dispatch
    ▼
GitHub Actions Workflow (.github/workflows/transcribe.yml)
    │
    │ downloads media safely (src/download_telegram_file.py)
    ▼
Local faster-whisper Transcription (src/transcribe.py)
    │
    │ sends TXT / SRT / VTT results & status notifications (src/telegram_notifier.py)
    ▼
Original Telegram Chat
```

---

## 🚀 Key Features

- **Local `faster-whisper` Inference**: Runs `faster-whisper` CPU `int8` quantization locally. Zero OpenAI API costs.
- **Dual Source Modes**: Supports both manual HTTPS URLs (`source_type=url`) and Telegram bot uploads (`source_type=telegram`).
- **Telegram Bot Webhook**: Lightweight FastAPI webhook listener triggers GitHub Actions workflows on-demand.
- **Immediate Response & Tracking**: Users receive an immediate "transcription queued" notice and real-time status updates in Telegram.
- **Strict Media Validation**: Uses `ffprobe` JSON probing to verify streams, container decoding, audio duration, and sample rate.
- **Multiple Output Formats**: Automatically exports and attaches `TXT`, `SRT`, `VTT`, and `JSON` subtitle files.
- **Large-File Fallback**: Handles Telegram's hosted 20 MB direct-download limit with a `/url <link>` command that reuses the secure HTTPS downloader.
- **Privacy & Security**: Token sanitization across all logs, non-root Docker container, per-user authorization whitelist, and automatic runner file cleanup.

---

## 🎛️ Workflow Inputs

When triggering the workflow manually via GitHub Actions (`workflow_dispatch`), the following inputs are supported:

| Input | Mode | Description | Default | Allowed Values / Examples |
| --- | --- | --- | --- | --- |
| `source_type` | Both | Media source selector | `url` | `url`, `telegram` |
| `audio_url` | `url` | HTTPS URL pointing to media file | *Empty* | `https://example.com/audio.mp3` |
| `telegram_file_id` | `telegram` | Telegram media file identifier | *Empty* | `AgACAgI...` |
| `telegram_chat_id` | `telegram` | Telegram chat ID | *Empty* | `123456789` |
| `telegram_status_message_id` | `telegram` | Telegram message ID to update | *Empty* | `42` |
| `request_id` | `telegram` | Unique transcription request UUID | *Empty* | `123e4567-e89b-12d3-a456-426614174000` |
| `language` | Both | Language code for transcription | `ar` | `ar`, `en`, `fr`, `auto` |
| `model` | Both | `faster-whisper` model size | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `output_formats` | Both | Comma-separated list of formats | `txt,srt,vtt,json` | Any combination of `txt`, `srt`, `vtt`, `json` |
| `vad_filter` | Both | Enable Voice Activity Detection | `true` | `true`, `false` |
| `word_timestamps` | Both | Include word-level timestamps | `true` | `true`, `false` |
| `initial_prompt` | Both | Vocabulary guide, names, or terms | *Empty* | `"اسم المنظمة، المصطلح التقني"` |
| `upload_artifacts` | Both | Artifact retention in Actions | `auto` | `auto`, `true`, `false` |

---

## 📁 Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── transcribe.yml        # GitHub Actions workflow definition
├── src/
│   ├── __init__.py
│   ├── audio_validator.py        # ffprobe JSON media probing & validation
│   ├── downloader.py             # Safe HTTPS streaming file downloader
│   ├── download_telegram_file.py # Secure Telegram Bot API media downloader
│   ├── subtitle_writer.py        # TXT, SRT, VTT, and JSON output generators
│   ├── telegram_notifier.py      # Telegram status update & output uploader
│   └── transcribe.py             # Main CLI transcription pipeline
├── telegram_bot/
│   ├── __init__.py
│   ├── app.py                    # FastAPI Webhook listener & commands
│   ├── config.py                 # Pydantic environment configuration
│   ├── github_client.py          # GitHub Actions workflow_dispatch client
│   ├── media.py                  # Telegram update parser & caption options
│   ├── state.py                  # SQLite request state & idempotency tracker
│   ├── telegram_client.py       # Telegram API client for bot updates
│   ├── requirements.txt          # Webhook bot service dependencies
│   └── Dockerfile                # Minimal non-root Docker container
├── tests/
│   ├── __init__.py
│   ├── test_audio_validator.py
│   ├── test_download_telegram_file.py
│   ├── test_downloader.py
│   ├── test_github_dispatch.py
│   ├── test_subtitle_writer.py
│   ├── test_telegram_media.py
│   ├── test_telegram_notifier.py
│   └── test_telegram_webhook.py
├── .env.example                  # Environment configuration template
├── docker-compose.telegram.yml   # Docker Compose manifest for bot service
├── requirements.txt              # Top-level dependencies & test requirements
└── README.md
```

---

## 🤖 Telegram Bot Integration Setup

### 1. Create Telegram Bot via BotFather
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the instructions to create your bot.
3. Save the returned `TELEGRAM_BOT_TOKEN`.

### 2. Generate Fine-Grained GitHub Token
1. Go to GitHub Settings -> Developer Settings -> Personal Access Tokens -> Fine-grained tokens.
2. Generate a new token scoped to your `audio` repository.
3. Grant **Repository permissions**: `Actions: Read and write`.
4. Save the generated `GITHUB_TOKEN`.

### 3. Add GitHub Repository Secret
In your GitHub repository:
1. Go to **Settings** -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret**.
3. Name: `TELEGRAM_BOT_TOKEN`.
4. Value: `<Your Telegram Bot Token>`.

### 4. Deploy Webhook Bot Service
Copy `.env.example` to `.env` and fill in your values:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_WEBHOOK_SECRET=your_generated_random_secret_string
ALLOWED_TELEGRAM_USER_IDS=12345678,87654321
GITHUB_TOKEN=github_pat_11ABCDEFG...
GITHUB_OWNER=your-github-username
GITHUB_REPO=audio
GITHUB_WORKFLOW_FILE=transcribe.yml
GITHUB_REF=main
```

Deploy using Docker Compose:

```bash
docker-compose -f docker-compose.telegram.yml up -d --build
```

### 5. Register Telegram Webhook
Register your webhook endpoint with Telegram (replace placeholders):

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain.com/telegram/webhook",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>"
  }'
```

Verify webhook registration:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

To remove or disable the webhook at any time:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

---

## 📱 Telegram User Instructions

### Supported Media Types
Send any of the following directly to your bot:
- **Audio / Music files** (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.opus`)
- **Voice messages**
- **Video clips / Video notes** (`.mp4`, `.mov`, `.mkv`, `.webm`)
- **Document files** (verified by MIME type / extension)

### Message Caption Options
You can customize transcription settings by adding key=value lines to your message caption:

```text
language=ar
model=small
formats=txt,srt
prompt=Names and technical vocabulary
```

### Large File Handling (> 20 MB)
If your file exceeds Telegram's direct upload limit (20 MB for hosted bots), send an HTTPS download link using:

```text
/url https://example.com/large-recording.mp3
```

---

## 🛠️ Local Usage & Testing

### 1. Requirements & Prerequisites
- Python 3.11+
- FFmpeg (`sudo apt-get install ffmpeg` on Ubuntu/Debian or `brew install ffmpeg` on macOS)

### 2. Installation
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run Unit Test Suite
```bash
python -m pytest tests/ -v
```

### 4. Run Manual Transcription
Transcribe an HTTPS URL:
```bash
python src/transcribe.py \
  --audio-url "https://example.com/sample.mp3" \
  --language "ar" \
  --model "small" \
  --output-dir "output"
```

Transcribe a local file:
```bash
python src/transcribe.py \
  --audio-file "path/to/recording.mp4" \
  --language "ar" \
  --model "small"
```

---

## 🔒 Security & Privacy

1. **Token Sanitization**: Bot tokens and secrets are redacted from exception outputs, logs, and HTTP request tracebacks.
2. **Authorized Access Only**: Unauthorized Telegram users (`user_id` check) receive a generic refusal notice without disclosing repository or infrastructure details.
3. **Webhook Verification**: Validates the `X-Telegram-Bot-Api-Secret-Token` header on every request.
4. **Public Repository Privacy**: In Telegram mode, raw audio files and transcripts are sent directly to Telegram and are NOT uploaded to public GitHub Actions artifacts unless `upload_artifacts=true` is set.
5. **Secret Rotation**: If a token is compromised:
   - Revoke the bot token with `@BotFather` using `/revoke`.
   - Revoke the GitHub PAT in GitHub Settings.
   - Update `TELEGRAM_BOT_TOKEN` in GitHub Secrets and `.env`.
   - Restart the webhook service.
