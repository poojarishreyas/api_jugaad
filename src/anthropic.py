"""Anthropic Messages API translation for browser-backed providers.

The browser provider can only return text, while Claude Code communicates with
the Messages API using structured content blocks.  This module keeps that
structure at the HTTP boundary and uses a small, explicit wire format when the
browser model needs Claude Code to run one of its local tools.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable


TOOL_CALLS_OPEN = "[[API_JUGAAD_TOOL_CALLS]]"
TOOL_CALLS_CLOSE = "[[/API_JUGAAD_TOOL_CALLS]]"
_TOOL_CALLS_PATTERN = re.compile(
    rf"{re.escape(TOOL_CALLS_OPEN)}\s*(.*?)\s*{re.escape(TOOL_CALLS_CLOSE)}",
    re.DOTALL,
)
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


class AnthropicAPIError(Exception):
    """An API error that is safe to serialize in Anthropic's error format."""

    def __init__(self, status_code: int, error_type: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class MessageResult:
    content: list[dict[str, Any]]
    stop_reason: str
    output_tokens: int


def estimate_tokens(value: Any) -> int:
    """Return a consistent conservative estimate when no native tokenizer exists."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(value) + 3) // 4)


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load_tool_calls(raw_json: str) -> Any | None:
    r"""Parse browser-produced JSON, repairing only invalid shell backslashes.

    Chat interfaces commonly emit shell fragments such as ``\(`` in an otherwise
    valid JSON tool call. JSON requires that backslash to be escaped as ``\\(``.
    Keep valid JSON untouched and only repair backslashes that cannot start a
    JSON escape sequence.
    """
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        try:
            return json.loads(_INVALID_JSON_ESCAPE.sub(r"\\\\", raw_json))
        except json.JSONDecodeError:
            return None


def _block_to_transcript(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return _as_json(block)

    block_type = block.get("type", "unknown")
    if block_type == "text":
        return str(block.get("text", ""))
    if block_type == "tool_use":
        return "[tool_use id={id} name={name} input={input}]".format(
            id=block.get("id", "unknown"),
            name=block.get("name", "unknown"),
            input=_as_json(block.get("input", {})),
        )
    if block_type == "tool_result":
        content = _content_to_transcript(block.get("content", ""))
        return "[tool_result tool_use_id={id} is_error={error}]\n{content}".format(
            id=block.get("tool_use_id", "unknown"),
            error=bool(block.get("is_error", False)),
            content=content,
        )
    if block_type in {"thinking", "redacted_thinking"}:
        # A browser UI cannot verify Anthropic thinking signatures.  Preserve a
        # marker so turn ordering is retained without replaying hidden reasoning.
        return f"[{block_type} block preserved by API adapter]"
    if block_type in {"image", "document"}:
        return f"[{block_type} attachment omitted: browser provider accepts text only]"
    return f"[{block_type} block] {_as_json(block)}"


def _content_to_transcript(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_block_to_transcript(block) for block in content)
    return _block_to_transcript(content)


def _system_to_transcript(system: Any) -> str:
    return _content_to_transcript(system) if system else ""


def _tool_catalog(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    catalog = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            continue
        catalog.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {"type": "object"}),
        })
    return catalog


def build_browser_prompt(body: dict[str, Any]) -> str:
    """Turn a Messages request into a complete, loss-aware browser prompt."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AnthropicAPIError(400, "invalid_request_error", "'messages' must be a non-empty array")

    transcript: list[str] = []
    system = _system_to_transcript(body.get("system"))
    if system:
        transcript.append(f"<system>\n{system}\n</system>")

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise AnthropicAPIError(400, "invalid_request_error", f"messages[{index}] must be an object")
        role = message.get("role")
        if role not in {"user", "assistant", "system"}:
            raise AnthropicAPIError(400, "invalid_request_error", f"messages[{index}].role is invalid")
        transcript.append(
            f"<{role}>\n{_content_to_transcript(message.get('content', ''))}\n</{role}>"
        )

    tools = _tool_catalog(body.get("tools"))
    tool_instructions = ""
    if tools:
        tool_choice = body.get("tool_choice") if isinstance(body.get("tool_choice"), dict) else {}
        choice_type = tool_choice.get("type")
        choice_instruction = ""
        if choice_type == "none":
            choice_instruction = "The client has disabled tool use for this turn; answer with text only."
        elif choice_type == "any":
            choice_instruction = "The client requires at least one tool call before a final answer."
        elif choice_type == "tool" and isinstance(tool_choice.get("name"), str):
            choice_instruction = f"The client requires the {tool_choice['name']} tool for this turn."
        tool_instructions = f"""
The client can execute only the tools in this catalog:
{_as_json(tools)}

When a tool is needed, do not describe the command and do not execute it yourself.
Reply with only this exact wrapper containing a JSON array of tool calls:
{TOOL_CALLS_OPEN}
[{{"name":"exact tool name","input":{{...}}}}]
{TOOL_CALLS_CLOSE}
The input must satisfy that tool's input_schema. Use ordinary text only when no
tool is needed. Never put a final answer outside the wrapper in a tool-use turn.
{choice_instruction}
"""

    return f"""You are the model behind a local Anthropic Messages API adapter used by
Claude Code. Follow the conversation's system instructions and answer the most
recent user request. The client, not you, executes tools and will send their
results in a later turn.{tool_instructions}

Conversation:
{chr(10).join(transcript)}
"""


def parse_browser_response(response_text: str, tools: Any) -> MessageResult:
    """Convert the browser model's explicit tool wrapper into Anthropic blocks."""
    text = response_text.strip()
    allowed_tools = {tool["name"] for tool in _tool_catalog(tools)}
    # Browser chat models often helpfully add an explanation before or after a
    # valid wrapper despite the instruction not to. Anthropic permits text and
    # tool_use blocks in the same assistant turn, so preserve that text instead
    # of losing the tool call.
    for match in _TOOL_CALLS_PATTERN.finditer(text):
        if not allowed_tools:
            break
        payload = _load_tool_calls(match.group(1))
        if payload is None:
            continue
        if isinstance(payload, dict):
            payload = payload.get("tool_calls")
        if isinstance(payload, list) and payload:
            calls: list[dict[str, Any]] = []
            for call in payload:
                if not isinstance(call, dict):
                    calls = []
                    break
                name, tool_input = call.get("name"), call.get("input", {})
                if name not in allowed_tools or not isinstance(tool_input, dict):
                    calls = []
                    break
                calls.append({
                    "type": "tool_use",
                    "id": f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": name,
                    "input": tool_input,
                })
            if calls:
                content: list[dict[str, Any]] = []
                before, after = text[:match.start()].strip(), text[match.end():].strip()
                if before:
                    content.append({"type": "text", "text": before})
                content.extend(calls)
                if after:
                    content.append({"type": "text", "text": after})
                return MessageResult(content, "tool_use", estimate_tokens(_as_json(content)))

    return MessageResult(
        [{"type": "text", "text": text}],
        "end_turn",
        estimate_tokens(text),
    )


def message_payload(result: MessageResult, model: str, input_tokens: int) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": result.content,
        "model": model,
        "stop_reason": result.stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": result.output_tokens},
    }


def _sse_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {_as_json(data)}\n\n"


def _stream_result(result: MessageResult) -> Iterable[str]:
    for index, block in enumerate(result.content):
        block_type = block["type"]
        if block_type == "text":
            yield _sse_event("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {"type": "text", "text": ""},
            })
            text = block.get("text", "")
            for start in range(0, len(text), 120):
                yield _sse_event("content_block_delta", {
                    "type": "content_block_delta", "index": index,
                    "delta": {"type": "text_delta", "text": text[start:start + 120]},
                })
        elif block_type == "tool_use":
            yield _sse_event("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {
                    "type": "tool_use", "id": block["id"], "name": block["name"], "input": {},
                },
            })
            yield _sse_event("content_block_delta", {
                "type": "content_block_delta", "index": index,
                "delta": {"type": "input_json_delta", "partial_json": _as_json(block["input"])},
            })
        yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": index})


async def stream_message(
    *,
    prompt: str,
    model: str,
    input_tokens: int,
    tools: Any,
    send_message,
    on_complete: Callable[[str, MessageResult], Awaitable[None]] | None = None,
    on_error: Callable[[str], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    """Start SSE immediately, emit keepalives while the browser UI is working."""
    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    yield _sse_event("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id, "type": "message", "role": "assistant", "content": [],
            "model": model, "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    })
    task = asyncio.create_task(send_message(prompt))
    try:
        while not task.done():
            try:
                response_text = await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except asyncio.TimeoutError:
                yield _sse_event("ping", {"type": "ping"})
            else:
                result = parse_browser_response(response_text, tools)
                if on_complete:
                    await on_complete(response_text, result)
                for event in _stream_result(result):
                    yield event
                yield _sse_event("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": result.stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": result.output_tokens},
                })
                yield _sse_event("message_stop", {"type": "message_stop"})
                return
        result = parse_browser_response(task.result(), tools)
        if on_complete:
            await on_complete(task.result(), result)
        for event in _stream_result(result):
            yield event
        yield _sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": result.stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": result.output_tokens},
        })
        yield _sse_event("message_stop", {"type": "message_stop"})
    except asyncio.CancelledError:
        if on_error:
            try:
                await on_error("Client disconnected before the response was complete.")
            except Exception:
                # A diagnostic capture must not prevent the request cleanup.
                pass
        raise
    except Exception as exc:
        if on_error:
            await on_error(str(exc))
        yield _sse_event("error", {
            "type": "error",
            "error": {"type": "api_error", "message": str(exc)},
        })
    finally:
        if not task.done():
            task.cancel()
