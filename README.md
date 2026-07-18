# API Jugaad 🤖

A local API server that turns **ChatGPT, Google Gemini, and Z.ai** into a real API — no paid subscription, no API keys from the provider. Just log in once in the browser window and start making requests.

Supports **OpenAI-compatible**, **Anthropic-compatible**, and a simple `/chat` endpoint — including full **streaming** (SSE), so tools like **Claude Code**, **Continue**, and **Open WebUI** work out of the box.

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
Lists available model (your active provider). Needed by Claude Code, Continue, Open WebUI.
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
Works with the Anthropic SDK and Claude Code. Supports `stream: true`, `system` prompt, and multi-turn messages.
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

**4. Streaming (exactly what Claude Code sends):**
```powershell
$body = '{"model":"claude-3-5-sonnet-20241022","max_tokens":100,"stream":true,"messages":[{"role":"user","content":"say hi in 5 words"}]}'
$req = [System.Net.HttpWebRequest]::Create("http://localhost:3000/v1/messages")
$req.Method = "POST"; $req.ContentType = "application/json"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$req.GetRequestStream().Write($bytes, 0, $bytes.Length)
$reader = New-Object System.IO.StreamReader($req.GetResponse().GetResponseStream())
while (-not $reader.EndOfStream) { Write-Host $reader.ReadLine() }
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
