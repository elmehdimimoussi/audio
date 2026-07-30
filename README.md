# GitHub Actions Audio & Video Transcriber (`faster-whisper`)

Production-ready GitHub Actions workflow and Python backend tool suite to transcribe long audio and video files (up to 2 hours) locally using `faster-whisper` on a CPU-hosted Ubuntu runner. No OpenAI API key required.

## 🚀 Key Features

- **Long-File Reliability**: Efficiently transcribes audio/video up to 2 hours long using `faster-whisper` CPU `int8` quantization and Silero VAD filtering.
- **Multiple Output Formats**: Automatically exports transcripts in `TXT`, `SRT`, `VTT`, and structured `JSON`.
- **Primary Arabic Support**: Defaults to Arabic (`ar`) with optional automatic language detection (`auto`) and custom vocabulary prompts.
- **Safe & Secure Downloader**: Enforces HTTPS, stream-to-disk size limits, redirect protection, and masked logging of sensitive URL parameters.
- **Strict Media Validation**: Uses `ffprobe` JSON probing to verify streams, container decoding, audio duration, and sample rate before running inference.
- **GitHub Actions Integration**: Built for `workflow_dispatch` with artifact uploading (7-day retention), step summary output, pip dependency caching, and Hugging Face model caching.

---

## 🎛️ Workflow Inputs

When triggering the workflow manually via GitHub Actions (`workflow_dispatch`), the following inputs are supported:

| Input | Description | Default | Allowed Values / Examples |
| --- | --- | --- | --- |
| `audio_url` | **Required** HTTPS URL pointing to audio/video file | *None* | `https://example.com/audio.mp3` |
| `language` | Language code for transcription | `ar` | `ar`, `en`, `fr`, `auto` |
| `model` | `faster-whisper` model size | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `output_formats` | Comma-separated list of formats | `txt,srt,vtt,json` | Any combination of `txt`, `srt`, `vtt`, `json` |
| `vad_filter` | Enable Voice Activity Detection | `true` | `true`, `false` |
| `word_timestamps` | Include word-level timestamps | `true` | `true`, `false` |
| `initial_prompt` | Vocabulary guide, names, or terms | *Empty* | `"اسم المنظمة، المصطلح التقني"` |

---

## 📁 Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── transcribe.yml    # GitHub Actions workflow definition
├── src/
│   ├── __init__.py
│   ├── audio_validator.py    # ffprobe JSON media probing & validation
│   ├── downloader.py         # Safe HTTPS streaming file downloader
│   ├── subtitle_writer.py    # TXT, SRT, VTT, and JSON output generators
│   └── transcribe.py         # Main CLI pipeline runner
├── tests/
│   ├── __init__.py
│   ├── test_audio_validator.py
│   ├── test_downloader.py
│   └── test_subtitle_writer.py
├── .gitignore
├── requirements.txt          # Python dependencies
└── README.md                 # Project documentation
```

---

## 🛠️ Local Usage

### 1. Requirements & Prerequisites
- Python 3.11+
- FFmpeg (`sudo apt-get install ffmpeg` on Ubuntu/Debian or `brew install ffmpeg` on macOS)

### 2. Installation
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run Test Suite
```bash
pytest tests/ -v
```

### 4. Run Transcription Locally
```bash
python src/transcribe.py \
  --audio-url "https://example.com/sample.mp3" \
  --language "ar" \
  --model "small" \
  --output-formats "txt,srt,vtt,json" \
  --vad-filter true \
  --word-timestamps true \
  --output-dir "output"
```

Or transcribe a local audio/video file directly:
```bash
python src/transcribe.py \
  --audio-file "path/to/recording.mp4" \
  --language "ar" \
  --model "small"
```

---

## 🔒 Security & Best Practices

1. **No Hardcoded Credentials**: All input URLs are sanitized prior to logging to ensure tokens and basic authentication parameters are redacted.
2. **Safe Downloader**: Only HTTPS URLs are accepted. Downloader aborts immediately if a response exceeds maximum allowed file sizes (default 2GB) or redirect thresholds.
3. **No Shell Injections**: GitHub Actions workflow variables are passed safely to the Python CLI via environment variables rather than raw shell string interpolations.
4. **UTF-8 Arabic Preservation**: Text processing uses standard UTF-8 encoding without altering or reversing right-to-left Arabic letter ordering.
