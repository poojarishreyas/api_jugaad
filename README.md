# API Jugaad 🤖

A local API server that turns **ChatGPT, Google Gemini, and Z.ai** into a real API — no paid subscription, no API keys from the provider. Just log in once in the browser window and start making requests.

Supports **OpenAI-compatible**, **Anthropic Messages-compatible**, and a simple `/chat` endpoint. Its Anthropic adapter understands Claude Code's structured messages, tool loop, and SSE protocol.

---

## How It Works

API Jugaad launches a real Chromium browser (via Playwright), logs you in once, and then drives the AI chat interface to fulfill API requests — scraping the response cleanly and returning it in the format you requested.

---

## Installation

**1. Create and activate a virtual environment:**
```bash
python -m venv venv
venv\Scripts\activate
```

**2. Install dependencies:**
```bash
pip install -r requirements.txt
playwright install chromium
```

**3. Configure `.env`** (copy from `.env.example`):
```env
PROVIDER=chatgpt   # Options: chatgpt, zai, gemini
PORT=3000
API_KEY=           # Optional: require a key for all requests
```

---

## Usage

```bash
python run.py
```

- Select your AI provider (or press Enter for ChatGPT)
- A browser window opens — **log in if prompted** (first run only)
- Once logged in, the API is live at `http://localhost:3000`

Sessions are saved automatically — you only log in once.

---

## Endpoints

### `GET /status`
Health check.
```bash
curl http://localhost:3000/status
```

---

### `GET /v1/models`
Lists Claude-shaped model IDs for gateway model discovery.
```bash
curl http://localhost:3000/v1/models
```

---

### `POST /chat` — Simple chat
```bash
curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```
```json
{ "response": "Hello! How can I help you?" }
```

---

### `POST /v1/chat/completions` — OpenAI-compatible
Works with any OpenAI SDK or tool. Supports `stream: true`.
```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

---

### `POST /v1/messages` — Anthropic-compatible
Supports Claude Code's `system` blocks, message history, tool definitions, `tool_use` / `tool_result` turns, adaptive-thinking fields, and `stream: true` SSE.
```bash
curl -X POST http://localhost:3000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "stream": false,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

---

## Using with Claude Code

Set these environment variables before launching Claude Code:

```bash
# Windows PowerShell
$env:ANTHROPIC_BASE_URL = "http://localhost:3000"
$env:ANTHROPIC_API_KEY  = "your-api-key"   # Match API_KEY in .env, or any string if unset

claude
```

```bash
# macOS / Linux
ANTHROPIC_BASE_URL=http://localhost:3000 \
ANTHROPIC_API_KEY=your-api-key \
claude
```

`ANTHROPIC_AUTH_TOKEN` also works if that is how your Claude Code setup authenticates. API Jugaad accepts both `Authorization: Bearer …` and `x-api-key`.

### What compatibility means here

Claude Code sends an Anthropic **Messages API** request, not a simple chat prompt. API Jugaad now translates its system blocks, conversation history, tool schemas, and tool results into the browser prompt. When the browser model chooses a tool, it is returned to Claude Code as a real Anthropic `tool_use` block; Claude Code executes it locally and sends the `tool_result` in the next request.

The browser websites do not expose their token stream to Playwright, so text is still scraped after the provider finishes generating. The server starts the SSE response immediately and sends heartbeats while it waits, which prevents Claude Code from treating the request as stalled, but it cannot match the first-token latency of a native Claude API.

### Additional Claude Code gateway routes

- `HEAD /` — safe gateway startup probe.
- `POST /v1/messages/count_tokens` — consistent local token estimate for context management.
- Anthropic-shaped error bodies and a `request-id` response header.

---

## API Key Auth

If `API_KEY` is set in `.env`, all endpoints require authentication.

Both formats are accepted:
```bash
# Header (OpenAI style)
curl -H "Authorization: Bearer your-key" ...

# Header (legacy)
curl -H "x-api-key: your-key" ...
```

## Capturing requests and responses

To save every AI request and response, add this to `.env` and restart the server:

```env
CAPTURE_RAW_REQUESTS=true
CAPTURE_DIRECTORY=captures
```

This creates one file per `/chat`, `/v1/chat/completions`, or `/v1/messages` request: `captures/000001.json`, `captures/000002.json`, and so on. Each file contains the raw API request (`request`), the translated browser prompt (`processed_request`), the raw browser response, and the final API response (or an error), so prompt 1 and response 1 stay together. If an SSE client disconnects early, its file is marked with an error instead of being left incomplete. `raw_request.json` still contains the newest request as a quick shortcut.

Captures include your conversation, system prompt, and tool definitions. They are gitignored and disabled by default; turn them off again after debugging.

---

## Testing Before Use

Run these in order to verify everything works:

**1. Status check:**
```powershell
Invoke-RestMethod -Uri "http://localhost:3000/status"
```

**2. Models list:**
```powershell
Invoke-RestMethod -Uri "http://localhost:3000/v1/models" | ConvertTo-Json -Depth 5
```

**3. Non-streaming Anthropic message:**
```powershell
Invoke-RestMethod -Uri "http://localhost:3000/v1/messages" `
  -Method Post -ContentType "application/json" `
  -Body '{"model":"claude-3-5-sonnet-20241022","max_tokens":100,"messages":[{"role":"user","content":"say hi in 5 words"}]}'
```

**4. Streaming (the Messages SSE protocol Claude Code uses):**
```powershell
$body = '{"model":"claude-3-5-sonnet-20241022","max_tokens":100,"stream":true,"messages":[{"role":"user","content":"say hi in 5 words"}]}'
$req = [System.Net.HttpWebRequest]::Create("http://localhost:3000/v1/messages")
$req.Method = "POST"; $req.ContentType = "application/json"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$req.GetRequestStream().Write($bytes, 0, $bytes.Length)
$reader = New-Object System.IO.StreamReader($req.GetResponse().GetResponseStream())
while (-not $reader.EndOfStream) { Write-Host $reader.ReadLine() }
```

**5. Token-count compatibility:**
```bash
curl -X POST http://localhost:3000/v1/messages/count_tokens \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Hello"}]}'
```

---

## Supported Providers

| Provider | Key | URL |
|---|---|---|
| ChatGPT | `chatgpt` | https://chatgpt.com |
| Google Gemini | `gemini` | https://gemini.google.com |
| Z.ai (Zhipu GLM) | `zai` | https://chat.z.ai |

---

## Project Structure

```
api_jugaad/
├── run.py                   # Entry point — select provider & start server
├── src/
│   ├── app.py               # FastAPI routes (chat, OpenAI, Anthropic endpoints)
│   ├── chat.py              # Request orchestration & asyncio lock
│   ├── browser.py           # Playwright browser lifecycle
│   ├── scraper.py           # Shared DOM → clean text extractor
│   ├── config.py            # Env config (PROVIDER, PORT, API_KEY)
│   └── providers/
│       ├── base.py          # Abstract provider interface
│       ├── chatgpt.py       # ChatGPT implementation
│       ├── gemini.py        # Gemini implementation
│       └── zai.py           # Z.ai implementation
└── .env                     # Your local config (gitignored)
```
