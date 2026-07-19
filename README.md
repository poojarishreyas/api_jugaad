# API Jugaad

> A local, browser-backed API bridge for ChatGPT, Gemini, and Z.ai with OpenAI-style and Anthropic Messages API endpoints.

API Jugaad drives an authenticated AI chat website through Playwright and exposes the result through a local FastAPI server. Its primary use case is experimenting with coding-agent clients—especially Claude Code—when a native provider API is not available.

It is an experimental local development tool, not an official provider integration or a replacement for a production model gateway.

## What it supports

| Capability | Status |
|---|---|
| Simple local chat endpoint | `POST /chat` |
| OpenAI-style chat completions | `POST /v1/chat/completions` |
| Anthropic Messages API adapter | `POST /v1/messages` |
| Claude Code tool loop | `tool_use` and `tool_result` translation |
| Anthropic SSE event format | Message, text, tool-use, ping, and error events |
| Claude Code gateway helpers | `HEAD /`, `/v1/models`, `/v1/messages/count_tokens` |
| Browser providers | ChatGPT, Google Gemini, Z.ai |
| Request/response debugging | One numbered JSON capture per exchange |

## How it works

```text
Claude Code / SDK
        │ Anthropic Messages API
        ▼
API Jugaad (FastAPI)
        │ translates structured history and tool schemas
        ▼
Playwright + authenticated browser chat
        │ browser response text
        ▼
API Jugaad
        │ Anthropic/OpenAI-shaped response
        ▼
Client
```

For Claude Code, the adapter preserves conversation history and tool results. When the browser model selects a tool, API Jugaad converts its response into an Anthropic `tool_use` block; Claude Code then runs the local tool and sends a `tool_result` in the next request.

## Requirements

- Python 3.10 or later
- Google Chrome installed locally (the server launches the Chrome channel through Playwright)
- A provider account you can log into in the browser window

## Installation

Clone the repository, then create a virtual environment.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Create your local configuration:

```bash
cp .env.example .env
```

```env
PORT=3000
API_KEY=
CAPTURE_RAW_REQUESTS=false
CAPTURE_DIRECTORY=captures
```

`API_KEY` is optional for local-only use. Set it before binding the server anywhere other than a trusted machine or network.

## Start the server

```bash
python run.py
```

Choose a provider when prompted. A Chrome window opens on first run; sign in there and keep the window open. The persistent browser profile is stored in `chrome-data/`, so you normally sign in only once.

The server listens on `http://localhost:3000` by default.

## Use with Claude Code

Start API Jugaad first, then launch Claude Code with a local Anthropic base URL.

### macOS / Linux

```bash
ANTHROPIC_BASE_URL=http://localhost:3000 \
ANTHROPIC_API_KEY=local-api-jugaad \
claude
```

### Windows PowerShell

```powershell
$env:ANTHROPIC_BASE_URL = "http://localhost:3000"
$env:ANTHROPIC_API_KEY = "local-api-jugaad"
claude
```

If `API_KEY` is configured in `.env`, use the same value for `ANTHROPIC_API_KEY`. The server also accepts `Authorization: Bearer <token>` for setups using `ANTHROPIC_AUTH_TOKEN`.

### Multiple agents

Claude Code may create several subagents or background tasks. API Jugaad serializes browser work through a single async lock because one browser page cannot safely run two chats at once. Waiting requests remain connected through SSE keepalive events rather than corrupting the browser state.

This means multiple agents are supported, but their model calls are processed one at a time. For predictable local runs, prefer a small number of foreground agents.

## API reference

| Endpoint | Purpose | Authentication |
|---|---|---|
| `GET /` and `HEAD /` | Gateway health probe | No |
| `GET /status` | Server and browser-queue status | No |
| `GET /v1/models` | Claude-shaped model discovery | No |
| `POST /chat` | Minimal chat endpoint | Optional API key |
| `POST /v1/chat/completions` | OpenAI-style chat completions | Optional API key |
| `POST /v1/messages` | Anthropic Messages API adapter | Optional API key |
| `POST /v1/messages/count_tokens` | Local token estimate | Optional API key |

### Simple chat

```bash
curl http://localhost:3000/chat \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"message":"Explain dependency injection in one paragraph."}'
```

### Anthropic Messages API

```bash
curl http://localhost:3000/v1/messages \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: local-api-jugaad' \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "Say hello in five words."}]
  }'
```

### Streaming Messages API

```bash
curl --no-buffer http://localhost:3000/v1/messages \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 512,
    "stream": true,
    "messages": [{"role": "user", "content": "Write a short greeting."}]
  }'
```

## Request and response captures

Enable exchange captures while debugging Claude Code or provider behavior:

```env
CAPTURE_RAW_REQUESTS=true
CAPTURE_DIRECTORY=captures
```

Each request creates one file:

```text
captures/
├── 000001.json  # request 1 + response 1
├── 000002.json  # request 2 + response 2
└── 000003.json  # request 3 + response 3
```

Every capture contains the incoming request, the translated browser prompt, the browser response, the final API response, timestamps, and any error. `raw_request.json` is also updated with the latest request as a quick inspection shortcut.

These files can include system prompts, file paths, tool definitions, and conversation content. They are gitignored; do not share them publicly.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `PORT` | `3000` | Local FastAPI port |
| `API_KEY` | empty | Optional key required by protected endpoints |
| `CAPTURE_RAW_REQUESTS` | `false` | Enables request/response capture files |
| `RAW_REQUEST_PATH` | `raw_request.json` | Latest-request shortcut path |
| `CAPTURE_DIRECTORY` | `captures` | Directory for numbered exchange captures |

## Architecture

```text
src/
├── app.py             HTTP routes, auth, capture wiring, response formatting
├── anthropic.py       Messages API translation, tool parsing, Anthropic SSE
├── browser.py         Persistent Playwright/Chrome lifecycle
├── capture.py         Atomic per-exchange JSON captures
├── chat.py            Single-browser request orchestration
├── scraper.py         Browser DOM response extraction
├── config.py          Environment configuration
└── providers/
    ├── base.py        Shared browser-chat provider behavior
    ├── chatgpt.py     ChatGPT selectors and metadata
    ├── gemini.py      Gemini selectors and metadata
    └── zai.py         Z.ai selectors and metadata
```

## Test

Run the protocol and capture tests without launching a browser:

```bash
python -m unittest discover -s tests -v
```

## Limitations and operational notes

- Browser interfaces do not expose native model tokens to Playwright. SSE begins immediately and sends keepalives, but generated text is available only after the browser response is complete.
- The bridge estimates tokens locally; it does not use Anthropic’s tokenizer.
- The browser adapter is text-first. Image and document blocks are represented as placeholders in the browser prompt.
- Website DOM structures, selectors, login flows, rate limits, and UI policies can change without notice.
- Tool-use conversion relies on the browser model following the adapter’s wrapper protocol. It is useful for experimentation but less reliable than a native model API.
- Browser session data and debug captures may contain sensitive information. Keep them local and out of source control.
- You are responsible for complying with the terms, policies, and account restrictions of every AI provider you use.

## Troubleshooting

### `address already in use`

Another server owns port 3000. Find and stop it, or change `PORT` in `.env`.

```bash
ss -ltnp 'sport = :3000'
```

### Browser opens but requests fail

Confirm that you are logged in to the selected provider in the Chrome window. If the site UI changed, inspect the provider selector definitions under `src/providers/`.

### Claude Code prints `[[API_JUGAAD_TOOL_CALLS]]`

Restart API Jugaad after updating the code. Enable captures and inspect the matching `captures/NNNNNN.json` file to see the browser response and translated API response.

### Claude Code seems slow with several agents

That is expected with one browser-backed provider: model requests queue behind the active browser chat. Reduce concurrent agents or use a native API for high-throughput workloads.

## Contributing

Contributions are welcome. When changing protocol behavior, please add or update a test under `tests/` and verify both structured Messages responses and SSE event order.
