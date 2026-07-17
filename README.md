# API Jugaad

> A self-hosted AI chat proxy that exposes a REST API by driving AI chatbot web UIs through a headless Puppeteer browser — no API keys required.

API Jugaad is a core micro-service in the **Lynx** project. It launches a stealth Chromium instance, authenticates with your existing session cookies, and forwards messages to your chosen AI provider via browser automation. The Lynx backend calls this service to power its multi-agent AI pipeline for full-stack application generation.

## Supported Providers

| Provider | Website | Model | Status |
|----------|---------|-------|--------|
| **ChatGPT** | [chatgpt.com](https://chatgpt.com) | GPT-4o / GPT-4 | ✅ Stable |
| **Z.ai** | [z.ai](https://z.ai) | GLM-5.2 (Zhipu) | ✅ Stable |
| **Gemini** | [gemini.google.com](https://gemini.google.com) | Gemini Pro / Flash | ⚠️ Experimental |

> **Note:** Z.ai and Gemini providers require you to inspect their web UIs and update the DOM selectors in `src/providers/zai.js` and `src/providers/gemini.js` respectively. See [Updating Selectors](#updating-selectors).

---

## How It Works

```
Client (Lynx Backend)
        │
        ▼
  POST /chat  ──►  Express Server
                        │
                        ▼
               Provider Factory (PROVIDER env var)
                   ┌────┼────┐
                   ▼    ▼    ▼
              ChatGPT  Z.ai  Gemini
                   │    │    │
                   ▼    ▼    ▼
               Puppeteer (Stealth Mode)
                        │
                        ▼
              AI Web UI (browser automation)
                        │
                        ▼
              Scraped Response ──► JSON back to client
```

1. On startup, a headless Chromium browser is launched with `puppeteer-extra` and the **stealth plugin** to avoid bot detection.
2. The **provider factory** loads the correct provider module based on the `PROVIDER` env var.
3. Provider-specific session cookies are injected from `.env`, authenticating the browser as your logged-in user.
   - **Auto-Login Feature:** If authentication fails (e.g. cookies are missing or expired), the Node server will automatically pause and launch the **Universal Login Helper** (a highly stealthy Python/Qt window). You simply log in manually, click "Save Cookies & Close", and the Node server automatically resumes, injects the new cookies, and starts the API!
4. When a `POST /chat` request arrives, the provider navigates to a fresh chat, types the message, clicks send, waits for the streaming response to complete, and scrapes the assistant's reply from the DOM.
5. A **mutex lock** ensures only one request is processed at a time (single browser tab).

---

## Tech Stack

| Component            | Technology                          |
| -------------------- | ----------------------------------- |
| Runtime              | Node.js 22                          |
| HTTP Server          | Express 4                           |
| Browser Automation   | Puppeteer 25 + puppeteer-extra      |
| Anti-Detection       | puppeteer-extra-plugin-stealth      |
| Configuration        | dotenv                              |
| Containerization     | Docker (Debian Bookworm Slim base)  |

---

## Project Structure

```
api_jugaad/
├── src/
│   ├── server.js           # Express app — routes, middleware, boot sequence
│   ├── chat.js             # Generic chat orchestrator — mutex, message flow
│   ├── browser.js          # Puppeteer launch, cookie injection, auth verification
│   ├── config.js           # Environment variables & provider selection
│   └── providers/
│       ├── index.js        # Provider factory — loads the active provider
│       ├── chatgpt.js      # ChatGPT provider — selectors, auth, scraping
│       ├── zai.js          # Z.ai provider — selectors, auth, scraping
│       └── gemini.js       # Gemini provider — selectors, auth, scraping
├── Dockerfile              # Production container with Chrome dependencies
├── .dockerignore
├── .gitignore
├── .env                    # Session tokens & config (not committed)
├── .env.example            # Template for .env
├── package.json
└── package-lock.json
```

---

## Setup

### Prerequisites

- **Node.js** ≥ 18 (22 recommended)
- An account on your chosen AI provider with an active session in your browser

### 1. Install Dependencies

```bash
cd api_jugaad
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` — set your provider and the corresponding session tokens:

```env
# Choose your provider: chatgpt | zai | gemini
PROVIDER=chatgpt
```

### 3. Get Session Tokens (Or use Auto-Login)

**Method 1: Universal Auto-Login (Recommended)**
The easiest way to get your session tokens is to simply run `npm start`. If you are not logged in, the server will automatically pop open a secure **Python QtWebEngine window**.
1. Log into your provider normally in this window. (Google Sign-In is fully supported and unblocked here thanks to advanced stealth scripts).
2. Click the green **Save Cookies & Close** button.
3. The script will automatically dump all required cookies directly into your `.env` file and seamlessly restart the API!

**Method 2: Manual Cookie Extraction**
If you prefer to manually extract cookies from your normal browser's DevTools (`F12` → **Application** → **Cookies**):

#### ChatGPT
1. Copy `__Secure-next-auth.session-token.0` → paste as `SESSION_TOKEN_0`.
2. Copy `__Secure-next-auth.session-token.1` → paste as `SESSION_TOKEN_1`.

#### Z.ai
1. Copy the main session/auth cookie (e.g. `acw_tc` or `oauth_id_token`) → paste as `ZAI_SESSION_COOKIE`. Or just use the Auto-Login feature which dumps the full cookie JSON array into `ZAI_COOKIES`.

#### Gemini
1. Copy `__Secure-1PSID` → paste as `GEMINI_PSID`.
2. Copy `__Secure-1PSIDTS` → paste as `GEMINI_PSIDTS`.
3. Copy `__Secure-1PSIDCC` → paste as `GEMINI_PSIDCC` (optional but recommended).

> **Note:** These tokens expire periodically. If the service throws an auth error, the Python auto-login window will automatically pop up to help you refresh them!

### 4. Start the Server

**Development** (with hot reload):
```bash
npm run dev
```

**Production**:
```bash
npm start
```

The server will launch Chromium, inject cookies for the selected provider, verify authentication, and start listening on the configured port.

---

## API Reference

### `POST /chat`

Send a message to the active AI provider and receive the response.

**Headers:**
| Header       | Required | Description                              |
| ------------ | -------- | ---------------------------------------- |
| Content-Type | Yes      | `application/json`                       |
| x-api-key    | No       | Required only if `API_KEY` is set in env |

**Request Body:**
```json
{
  "message": "Explain closures in JavaScript"
}
```

**Success Response** (`200`):
```json
{
  "response": "A closure is a function that remembers the variables from its outer scope..."
}
```

**Error Responses:**

| Status | Reason                                         |
| ------ | ---------------------------------------------- |
| 400    | Missing or empty `message` field               |
| 401    | Invalid or missing `x-api-key` header          |
| 429    | Server busy processing another request         |
| 500    | Internal error (auth failure, DOM change, etc) |

**Example (cURL):**
```bash
curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Docker?"}'
```

---

### `POST /v1/chat/completions`

OpenAI-compatible endpoint. This allows you to use API Jugaad as a drop-in replacement for the OpenAI API in standard tools and extensions. The messages array is flattened into a single prompt before being sent to the provider.

**Request Body (Standard OpenAI format):**
```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "You are a coding assistant."},
    {"role": "user", "content": "Write a python script."}
  ]
}
```

#### VS Code Extension Integration (Cline, Roo Code, Continue.dev, etc.)

You can plug API Jugaad directly into AI coding assistants in VS Code:

1. Open your extension's settings (e.g. Cline settings)
2. Select **API Provider**: `OpenAI Compatible`
3. Set **Base URL**: `http://localhost:3000/v1`
4. Set **API Key**: (leave blank, or put any dummy text if required)
5. Set **Model**: (leave blank, or put `zai` / `chatgpt`)

*Note: Since web UI chatbots don't natively support "System" prompts, API Jugaad simply concatenates all messages in the history into one big prompt before typing it into the chat box.*

---

### `POST /v1/messages`

Anthropic-compatible endpoint. This allows you to use API Jugaad natively with tools built for Anthropic APIs, like the official **Claude Code** CLI and VS Code extension.

**Request Body (Standard Anthropic format):**
```json
{
  "model": "claude-3-5-sonnet-20241022",
  "system": "You are a coding assistant.",
  "messages": [
    {"role": "user", "content": "Write a python script."}
  ]
}
```

#### Claude Code (Anthropic CLI / VS Code Extension) Integration

The official Claude Code tool doesn't have UI settings for a custom backend, but it reads environment variables. You can tell it to use API Jugaad by setting the `ANTHROPIC_BASE_URL` before running it:

**In your terminal:**
```bash
export ANTHROPIC_BASE_URL="http://localhost:3000"
export ANTHROPIC_API_KEY="dummy-key"
claude
```

If you are using the VS Code Claude panel (`claudeCode.preferredLocation`), make sure you launch VS Code from a terminal where those environment variables are exported, or add them to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Add to ~/.zshrc or ~/.bashrc
export ANTHROPIC_BASE_URL="http://localhost:3000"
export ANTHROPIC_API_KEY="dummy-key"
```

---

### `GET /status`

Health check endpoint — includes the active provider name.

**Response:**
```json
{
  "status": "ok",
  "busy": false,
  "provider": "chatgpt"
}
```

---

## Docker

### Standalone

```bash
docker build -t api-jugaad ./api_jugaad
docker run -d \
  --name api-jugaad \
  --shm-size=512m \
  --env-file ./api_jugaad/.env \
  -e PROVIDER=chatgpt \
  -p 3000:3000 \
  api-jugaad
```

> **Important:** `--shm-size=512m` is required for Chrome to run without crashing inside Docker.

### With Lynx (Docker Compose)

API Jugaad is included in the Lynx `docker-compose.yml`. Set the provider via environment:

```bash
# Default (ChatGPT)
docker compose up -d

# Use Z.ai
PROVIDER=zai docker compose up -d

# Use Gemini
PROVIDER=gemini docker compose up -d
```

---

## Updating Selectors

The Z.ai and Gemini providers ship with **best-effort selectors** that may need updating when their UIs change. To find the correct selectors:

1. Open the provider's website in your browser and log in.
2. Open DevTools (`F12`) → **Elements** tab.
3. Use the element picker (🔍) to locate:
   - **Input box** — where you type messages
   - **Send button** — the button that sends the message
   - **Stop button** — appears during streaming (if applicable)
   - **Assistant message** — the container for AI responses
4. Note the CSS selector for each element.
5. Update the `SELECTORS` object in the corresponding provider file:
   - `src/providers/zai.js` for Z.ai
   - `src/providers/gemini.js` for Gemini

---

## Architecture Notes

- **Provider Pattern:** Each provider implements the same interface (`getCookies`, `verifyAuth`, `typeMessage`, `clickSend`, `waitForResponse`, `scrapeResponse`, `startNewChat`). Adding a new provider is just creating a new file in `src/providers/`.
- **Stealth Mode:** Uses `puppeteer-extra-plugin-stealth` to patch Chromium's fingerprint, evading bot detection.
- **Mutex Locking:** Since only one browser tab is used, a JavaScript mutex ensures requests are serialized. Concurrent requests receive a `429` response.
- **New Chat per Request:** Each API call navigates to a fresh chat to prevent context bleed between unrelated prompts.
- **DOM Scraping:** The scraper handles both code blocks (`<pre><code>`) and inline text. For inline `<code>` elements, backtick delimiters stripped by the markdown renderer are restored to preserve content fidelity.
- **Multi-Strategy Response Detection:** Z.ai and Gemini providers use fallback strategies (stop button → loading indicator → DOM stabilization) to detect when a response is complete.

---

## Adding a New Provider

1. Create `src/providers/<name>.js` implementing the provider interface.
2. Register it in `src/providers/index.js`.
3. Add the corresponding token variables to `config.js` and `.env`.
4. Set `PROVIDER=<name>` in your `.env`.

---

## Troubleshooting

| Problem                            | Solution                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------ |
| `Session token invalid or expired` | The Python auto-login window should open. If not, refresh tokens manually|
| `Input box not found`              | The provider's UI may have changed — update selectors in `src/providers/` |
| `Unknown provider "xyz"`           | Check `PROVIDER` in `.env` — must be one of: `chatgpt`, `zai`, `gemini` |
| Chrome crashes in Docker           | Ensure `--shm-size=512m` is set; the default 64MB shared memory is insufficient |
| `Server is busy` (429)             | Wait for the current request to complete; only one request at a time     |
| `Failed to start: The browser is already running` | You have a lingering Puppeteer Chrome window open (or an old server is stuck in the background). Close all Chrome windows or run `taskkill /F /IM node.exe` to kill stuck servers. |
| `Listen error: EADDRINUSE :::3000` | You started `npm start` multiple times without killing the first one. Run `taskkill /F /IM node.exe` and try again. |
| CAPTCHA / bot detection            | Let the Python auto-login window handle it, or use `headless: false` locally to solve manually. |
| Gemini blocks automation           | Google has aggressive anti-bot detection; try reducing request frequency  |

---

## License

Part of the [Lynx](../) project.
