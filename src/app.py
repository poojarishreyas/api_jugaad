from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
import uuid
import time
import json
import asyncio

from contextlib import asynccontextmanager
from .config import config
from . import chat

# ---------------------------------------------------------------------------
# Lifespan: init browser + auth check on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from . import browser
    worker = await browser.init_browser()
    provider = chat._provider
    if provider:
        print(f"[*] Navigating to {provider.url}...")
        await worker.page.goto(provider.url)
        print(f"[*] Checking auth for {provider.name}...")
        is_auth = await provider.verify_auth(worker)
        if not is_auth:
            print(f"\n[!] Not logged in or session invalid.")
            print(f"[!] Please log in directly in the browser window.")
            print(f"[!] Once logged in, your session will be saved automatically.")
            print(f"[!] Keep the window open.\n")
        else:
            print(f"\n[*] Logged in successfully!")
            print(f"[*] API Jugaad is ready to receive requests on http://localhost:{config.PORT}/\n")
    yield
    print("[*] Shutting down browser...")
    await worker.close()

app = FastAPI(title="API Jugaad", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

async def verify_api_key(request: Request):
    if not config.API_KEY:
        return
    key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if key != config.API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid or missing API key")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_prompt(messages: list, system: str = "") -> str:
    """
    Convert a messages array into a single prompt string.
    Prepends system prompt if provided.
    """
    parts = []
    if system:
        parts.append(f"SYSTEM: {system}")
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        # content can be a string or a list of blocks (Anthropic format)
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


async def _anthropic_sse_stream(response_text: str, model: str, input_tokens: int):
    """
    Emit a complete Anthropic SSE stream from a fully-scraped response.

    Claude Code (and the Anthropic SDK with stream=True) expects these
    events in order:
      message_start → content_block_start → ping →
      content_block_delta* → content_block_stop →
      message_delta → message_stop
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    output_tokens = max(1, len(response_text) // 4)

    def event(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    # message_start
    yield event("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 1},
        },
    })

    # content_block_start
    yield event("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    # ping (expected by Anthropic SDK)
    yield event("ping", {"type": "ping"})

    # content_block_delta — send in ~50-char chunks so the client
    # starts processing immediately rather than waiting for one huge blob
    CHUNK = 50
    for i in range(0, len(response_text), CHUNK):
        yield event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": response_text[i:i + CHUNK]},
        })

    # content_block_stop
    yield event("content_block_stop", {"type": "content_block_stop", "index": 0})

    # message_delta
    yield event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })

    # message_stop
    yield event("message_stop", {"type": "message_stop"})


async def _openai_sse_stream(response_text: str, model: str):
    """
    Emit an OpenAI-compatible SSE stream (chat.completion.chunk format).
    """
    cid = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict, finish_reason=None) -> str:
        data = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }],
        }
        return f"data: {json.dumps(data)}\n\n"

    # role chunk
    yield chunk({"role": "assistant", "content": ""})

    # content chunks (~50 chars each)
    CHUNK = 50
    for i in range(0, len(response_text), CHUNK):
        yield chunk({"content": response_text[i:i + CHUNK]})

    # stop chunk
    yield chunk({}, finish_reason="stop")

    yield "data: [DONE]\n\n"

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/status")
def get_status():
    return {
        "status": "online",
        "provider": chat.get_provider_name(),
        "busy": chat.is_busy(),
    }


@app.get("/v1/models")
async def list_models(_: Request = None):
    """Stub models list — needed by some clients (e.g. Continue, Open WebUI)."""
    name = chat.get_provider_name()
    return {
        "object": "list",
        "data": [{
            "id": name,
            "object": "model",
            "created": 0,
            "owned_by": "api-jugaad",
        }],
    }


@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def simple_chat(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = body.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="'message' field is required")

    if chat.is_busy():
        raise HTTPException(status_code=429, detail="A request is already in progress. Try again shortly.")

    try:
        response = await chat.send_message(message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def openai_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="'messages' array is required")

    model = body.get("model", chat.get_provider_name())
    stream = body.get("stream", False)
    system = body.get("system", "")
    prompt = _build_prompt(messages, system)

    if chat.is_busy():
        raise HTTPException(status_code=429, detail="A request is already in progress. Try again shortly.")

    try:
        response_text = await chat.send_message(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if stream:
        return StreamingResponse(
            _openai_sse_stream(response_text, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response_text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(prompt) // 4,
            "completion_tokens": len(response_text) // 4,
            "total_tokens": (len(prompt) + len(response_text)) // 4,
        },
    }


@app.post("/v1/messages", dependencies=[Depends(verify_api_key)])
async def anthropic_messages(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="'messages' array is required")

    model = body.get("model", chat.get_provider_name())
    stream = body.get("stream", False)
    system = body.get("system", "")  # Anthropic system prompt field
    prompt = _build_prompt(messages, system)
    input_tokens = max(1, len(prompt) // 4)

    if chat.is_busy():
        raise HTTPException(status_code=429, detail="A request is already in progress. Try again shortly.")

    try:
        response_text = await chat.send_message(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── Streaming response (required by Claude Code) ──────────────────────
    if stream:
        return StreamingResponse(
            _anthropic_sse_stream(response_text, model, input_tokens),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Non-streaming response ────────────────────────────────────────────
    return {
        "id": f"msg_{uuid.uuid4()}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": response_text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": max(1, len(response_text) // 4),
        },
    }
