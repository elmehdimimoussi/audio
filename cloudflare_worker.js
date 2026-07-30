/**
 * Cloudflare Worker for Telegram Webhook -> GitHub Actions Workflow Dispatch
 * 
 * 100% Free, No Credit Card Required, No Server Needed.
 * Deploy via Cloudflare Dashboard (Workers & Pages -> Create Worker -> Edit code).
 * 
 * Copy and paste this entire code into the Cloudflare Worker Editor and click "Save and Deploy".
 */

// Default Configuration & Credentials Fallback
const CONFIG = {
  TELEGRAM_BOT_TOKEN: "",
  TELEGRAM_WEBHOOK_SECRET: "",
  ALLOWED_TELEGRAM_USER_IDS: "7922949424",
  GITHUB_TOKEN: "",
  GITHUB_OWNER: "elmehdimimoussi",
  GITHUB_REPO: "audio",
  GITHUB_WORKFLOW_FILE: "transcribe.yml",
  GITHUB_REF: "main",
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Merge Environment Variables from Cloudflare Dashboard with default CONFIG
    const botToken = env.TELEGRAM_BOT_TOKEN || CONFIG.TELEGRAM_BOT_TOKEN;
    const webhookSecret = env.TELEGRAM_WEBHOOK_SECRET || CONFIG.TELEGRAM_WEBHOOK_SECRET;
    const allowedUserIdsStr = env.ALLOWED_TELEGRAM_USER_IDS || CONFIG.ALLOWED_TELEGRAM_USER_IDS;
    const githubToken = env.GITHUB_TOKEN || CONFIG.GITHUB_TOKEN;
    const githubOwner = env.GITHUB_OWNER || CONFIG.GITHUB_OWNER;
    const githubRepo = env.GITHUB_REPO || CONFIG.GITHUB_REPO;
    const githubWorkflow = env.GITHUB_WORKFLOW_FILE || CONFIG.GITHUB_WORKFLOW_FILE;
    const githubRef = env.GITHUB_REF || CONFIG.GITHUB_REF;

    // 1. Health check endpoint
    if (request.method === "GET" && url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", service: "cloudflare-telegram-worker" }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    }

    // 2. Only process POST /telegram/webhook
    if (request.method !== "POST" || url.pathname !== "/telegram/webhook") {
      return new Response("Not Found", { status: 404 });
    }

    // 3. Verify Secret Header
    const secretHeader = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (webhookSecret && secretHeader !== webhookSecret) {
      return new Response("Forbidden", { status: 403 });
    }

    try {
      const update = await request.json();
      const message = update.message || update.edited_message;
      if (!message) {
        return new Response(JSON.stringify({ status: "ignored_no_message" }), { status: 200 });
      }

      const userId = message.from?.id;
      const chatId = message.chat?.id;
      const messageId = message.message_id;

      if (!userId || !chatId) {
        return new Response(JSON.stringify({ status: "ignored_no_ids" }), { status: 200 });
      }

      // 4. Authorization check
      const allowedUsers = (allowedUserIdsStr || "").split(",").map(u => u.trim()).filter(Boolean);
      if (allowedUsers.length > 0 && !allowedUsers.includes(String(userId))) {
        await sendTelegramMessage(botToken, chatId, "⚠️ Not authorized to use this bot.");
        return new Response(JSON.stringify({ status: "user_unauthorized" }), { status: 200 });
      }

      const text = (message.text || "").trim();

      // 5. Handle Commands (/start, /help, /url)
      if (text.startsWith("/start") || text.startsWith("/help")) {
        const helpText = "🎙️ <b>faster-whisper Transcription Bot</b>\n\nSend me audio, voice, video, or supported document files to transcribe!";
        await sendTelegramMessage(botToken, chatId, helpText);
        return new Response(JSON.stringify({ status: "command_handled" }), { status: 200 });
      }

      if (text.startsWith("/url")) {
        const audioUrl = text.replace("/url", "").trim();
        if (!audioUrl.startsWith("https://")) {
          await sendTelegramMessage(botToken, chatId, "⚠️ Please provide a valid <code>https://</code> URL.");
          return new Response(JSON.stringify({ status: "invalid_url" }), { status: 200 });
        }
        const requestId = crypto.randomUUID();
        const smid = await sendTelegramMessage(botToken, chatId, `✅ Request received (URL Mode).\nRequest ID: <code>${requestId.slice(0, 8)}</code>`, messageId);
        await dispatchGitHubWorkflow({
          githubToken, githubOwner, githubRepo, githubWorkflow, githubRef
        }, {
          source_type: "url",
          audio_url: audioUrl,
          request_id: requestId,
          language: "ar",
          model: "medium",
          output_formats: "txt",
          vad_filter: "true",
          word_timestamps: "true",
          initial_prompt: "",
        });
        return new Response(JSON.stringify({ status: "url_dispatched" }), { status: 200 });
      }

      // 6. Extract Media File
      const media = message.audio || message.voice || message.video || message.video_note || message.document;
      if (!media || !media.file_id) {
        return new Response(JSON.stringify({ status: "no_media_ignored" }), { status: 200 });
      }

      const requestId = crypto.randomUUID();
      const statusText = `✅ <b>Transcription request received.</b>\n\n• <b>Request ID:</b> <code>${requestId.slice(0, 13)}</code>\n• <b>Language:</b> <code>ar</code>\n• <b>Model:</b> <code>medium</code>\n• <b>Status:</b> <code>queued</code>`;
      
      const smid = await sendTelegramMessage(botToken, chatId, statusText, messageId);

      // 7. Dispatch GitHub Actions Workflow
      const dispatchOk = await dispatchGitHubWorkflow({
        githubToken, githubOwner, githubRepo, githubWorkflow, githubRef
      }, {
        source_type: "telegram",
        telegram_file_id: media.file_id,
        telegram_chat_id: String(chatId),
        telegram_status_message_id: smid ? String(smid) : "",
        request_id: requestId,
        language: "ar",
        model: "medium",
        output_formats: "txt",
        vad_filter: "true",
        word_timestamps: "true",
        initial_prompt: "",
      });

      if (!dispatchOk && smid) {
        await editTelegramMessage(botToken, chatId, smid, "❌ GitHub Workflow Dispatch Failed.");
      }

      return new Response(JSON.stringify({ status: "dispatched" }), { status: 200 });

    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), { status: 200 });
    }
  }
};

async function sendTelegramMessage(token, chatId, text, replyToId = null) {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const body = { chat_id: chatId, text, parse_mode: "HTML" };
  if (replyToId) body.reply_to_message_id = replyToId;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return data.ok ? data.result?.message_id : null;
}

async function editTelegramMessage(token, chatId, messageId, text) {
  const url = `https://api.telegram.org/bot${token}/editMessageText`;
  const body = { chat_id: chatId, message_id: messageId, text, parse_mode: "HTML" };
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function dispatchGitHubWorkflow(cfg, inputs) {
  const url = `https://api.github.com/repos/${cfg.githubOwner}/${cfg.githubRepo}/actions/workflows/${cfg.githubWorkflow}/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${cfg.githubToken}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "Cloudflare-Worker-Whisper-Bot",
    },
    body: JSON.stringify({ ref: cfg.githubRef, inputs }),
  });

  return res.status === 204 || res.status === 200 || res.status === 201;
}
