"""HTTP API surface for API Jugaad."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import chat
from .anthropic import (
    AnthropicAPIError,
    build_browser_prompt,
    estimate_tokens,
    extract_working_directory,
    message_payload,
    parse_browser_response,
    stream_message,
)
from .config import config
from .capture import ExchangeCapture


@asynccontextmanager
async def lifespan(app: FastAPI):
    from . import browser

    worker = await browser.init_browser()
    provider = chat._provider
    if provider:
        print(f"[*] Navigating to {provider.url}...")
        await worker.page.goto(provider.url)
        print(f"[*] Checking auth for {provider.name}...")
        if await provider.verify_auth(worker):
            print(f"[*] API Jugaad is ready at http://localhost:{config.PORT}/")
        else:
            print("[!] Log in directly in the browser window, then keep it open.")
    yield
    print("[*] Shutting down browser...")
    await worker.close()


app = FastAPI(title="API Jugaad", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = f"req_{uuid.uuid4().hex[:24]}"
    response = await call_next(request)
    response.headers["request-id"] = request.state.request_id
    return response


@app.exception_handler(AnthropicAPIError)
async def anthropic_error_handler(request: Request, exc: AnthropicAPIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "error",
            "error": {"type": exc.error_type, "message": exc.message},
            "request_id": getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:24]}"),
        },
    )


async def verify_api_key(request: Request):
    if not config.API_KEY:
        return
    supplied = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not supplied or not secrets.compare_digest(supplied, config.API_KEY):
        raise AnthropicAPIError(401, "authentication_error", "Invalid or missing API key")


async def request_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AnthropicAPIError(400, "invalid_request_error", "Invalid JSON body")
    if not isinstance(body, dict):
        raise AnthropicAPIError(400, "invalid_request_error", "Request body must be a JSON object")
    return body


def _write_raw_request(body: dict[str, Any]) -> None:
    """Atomically replace the opt-in newest-request shortcut file."""
    target = config.RAW_REQUEST_PATH
    directory = os.path.dirname(target) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".raw_request.", suffix=".json", delete=False
    ) as temporary:
        json.dump(body, temporary, indent=2, ensure_ascii=False)
        temporary.write("\n")
        temporary_path = temporary.name
    os.replace(temporary_path, target)


async def start_exchange_capture(
    body: dict[str, Any], endpoint: str, processed_request: str
) -> ExchangeCapture | None:
    """Start an opt-in capture without making debugging storage an API failure."""
    if not config.CAPTURE_RAW_REQUESTS:
        return None
    try:
        await asyncio.to_thread(_write_raw_request, body)
        return await asyncio.to_thread(
            ExchangeCapture.start,
            config.CAPTURE_DIRECTORY,
            body,
            endpoint=endpoint,
            processed_request=processed_request,
        )
    except OSError as exc:
        print(f"[capture] Could not write request capture: {exc}")
        return None


def captured_message_result(result, model: str, input_tokens: int) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": result.content,
        "model": model,
        "stop_reason": result.stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": result.output_tokens},
    }


def _openai_stream(response_text: str, model: str):
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    def event(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }) + "\n\n"

    yield event({"role": "assistant", "content": ""})
    for start in range(0, len(response_text), 120):
        yield event({"content": response_text[start:start + 120]})
    yield event({}, "stop")
    yield "data: [DONE]\n\n"


@app.get("/")
@app.head("/")
async def root_probe():
    """Claude Code may probe the configured gateway before its first request."""
    return Response(status_code=200)


@app.get("/status")
async def get_status():
    return {"status": "online", "provider": chat.get_provider_name(), "busy": chat.is_busy()}


@app.get("/v1/models")
async def list_models():
    """Expose Claude-shaped IDs so Claude Code model discovery can use this gateway."""
    provider = chat.get_provider_name()
    return {
        "object": "list",
        "data": [
            {"id": "claude-opus-4-8", "object": "model", "display_name": f"API Jugaad Opus ({provider})", "created": 0, "owned_by": "api-jugaad"},
            {"id": "claude-sonnet-4-6", "object": "model", "display_name": f"API Jugaad Sonnet ({provider})", "created": 0, "owned_by": "api-jugaad"},
        ],
    }


@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def simple_chat(request: Request):
    body = await request_body(request)
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        raise AnthropicAPIError(400, "invalid_request_error", "'message' must be a non-empty string")
    capture = await start_exchange_capture(body, "/chat", message)
    try:
        response_text = await chat.send_message(message)
        response = {"response": response_text}
        if capture:
            await asyncio.to_thread(capture.complete, browser_response=response_text, api_response=response)
        return response
    except Exception as exc:
        if capture:
            await asyncio.to_thread(capture.fail, str(exc))
        raise AnthropicAPIError(500, "api_error", str(exc))


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def openai_completions(request: Request):
    body = await request_body(request)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AnthropicAPIError(400, "invalid_request_error", "'messages' must be a non-empty array")
    prompt = build_browser_prompt({"messages": messages})
    capture = await start_exchange_capture(body, "/v1/chat/completions", prompt)

    model = body.get("model") or chat.get_provider_name()
    try:
        response_text = await chat.send_message(prompt)
    except AnthropicAPIError:
        raise
    except Exception as exc:
        if capture:
            await asyncio.to_thread(capture.fail, str(exc))
        raise AnthropicAPIError(500, "api_error", str(exc))

    prompt_tokens = estimate_tokens(messages)
    completion_tokens = estimate_tokens(response_text)
    response = {
        "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    }
    if capture:
        await asyncio.to_thread(capture.complete, browser_response=response_text, api_response=response)
    if body.get("stream"):
        return StreamingResponse(_openai_stream(response_text, model), media_type="text/event-stream")
    return response


@app.post("/v1/messages/count_tokens", dependencies=[Depends(verify_api_key)])
async def count_anthropic_tokens(request: Request):
    body = await request_body(request)
    return {"input_tokens": estimate_tokens(build_browser_prompt(body))}


@app.post("/v1/messages", dependencies=[Depends(verify_api_key)])
async def anthropic_messages(request: Request):
    body = await request_body(request)
    prompt = build_browser_prompt(body)
    model = body.get("model") or "claude-sonnet-4-6"
    if not isinstance(model, str):
        raise AnthropicAPIError(400, "invalid_request_error", "'model' must be a string")
    input_tokens = estimate_tokens(prompt)
    working_directory = extract_working_directory(body)
    capture = await start_exchange_capture(body, "/v1/messages", prompt)

    if body.get("stream"):
        async def capture_complete(browser_response, result):
            if capture:
                await asyncio.to_thread(
                    capture.complete,
                    browser_response=browser_response,
                    api_response=captured_message_result(result, model, input_tokens),
                )

        async def capture_error(message):
            if capture:
                await asyncio.to_thread(capture.fail, message)

        # Start the SSE response now. The browser UI is still buffered, but pings
        # keep Claude Code's connection alive while it produces the response.
        return StreamingResponse(
            stream_message(
                prompt=prompt, model=model, input_tokens=input_tokens,
                tools=body.get("tools"), send_message=chat.send_message,
                working_directory=working_directory,
                on_complete=capture_complete, on_error=capture_error,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        response_text = await chat.send_message(prompt)
    except Exception as exc:
        if capture:
            await asyncio.to_thread(capture.fail, str(exc))
        raise AnthropicAPIError(500, "api_error", str(exc))
    result = parse_browser_response(response_text, body.get("tools"), working_directory)
    response = message_payload(result, model, input_tokens)
    if capture:
        await asyncio.to_thread(capture.complete, browser_response=response_text, api_response=response)
    return response
