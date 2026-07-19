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
from pathlib import PurePath
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable


TOOL_CALLS_OPEN = "[[API_JUGAAD_TOOL_CALLS]]"
TOOL_CALLS_CLOSE = "[[/API_JUGAAD_TOOL_CALLS]]"
_TOOL_CALLS_PATTERN = re.compile(
    rf"{re.escape(TOOL_CALLS_OPEN)}\s*(.*?)\s*{re.escape(TOOL_CALLS_CLOSE)}",
    re.DOTALL,
)
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')
_WORKING_DIRECTORY = re.compile(r"Primary working directory:\s*([^\n]+)")
_HTML_DOCUMENT = re.compile(r"(?is)(<!doctype\s+html\b.*?</html>)")


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
    r"""Parse browser-produced JSON with progressive repair passes.

    Pass 1: strict json.loads.
    Pass 2: repair invalid shell backslashes (e.g. ``\(`` → ``\\(``).
    Pass 3: escape bare double-quotes inside JSON string values — these appear
            when a browser model embeds HTML attribute strings like
            onclick="fn()" directly inside a JSON string without escaping.
    """
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        pass
    repaired = _INVALID_JSON_ESCAPE.sub(r"\\\\", raw_json)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    # Pass 3: inside JSON string values, replace bare " that are not already
    # escaped and not the string delimiter.  Strategy: use the json module's
    # error position to find the bad offset and escape it, repeat until clean.
    attempt = repaired
    for _ in range(20):  # guard against infinite loop
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            pos = exc.pos
            if pos <= 0 or pos >= len(attempt):
                break
            if attempt[pos] != '"':
                break
            attempt = attempt[:pos] + '\\"' + attempt[pos + 1:]
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


def _compact_tool_catalog(tools: Any) -> list[dict[str, Any]]:
    """Give the browser only action names and fields, not Claude Code's harness."""
    compact = []
    for tool in _tool_catalog(tools):
        schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        compact.append({
            "name": tool["name"],
            "required": schema.get("required", []),
            "input_fields": list(properties),
        })
    return compact


def extract_working_directory(body: dict[str, Any]) -> str | None:
    """Read Claude Code's workspace hint without forwarding its full harness."""
    values = [_content_to_transcript(body.get("system", ""))]
    values.extend(_content_to_transcript(message.get("content", "")) for message in body.get("messages", []) if isinstance(message, dict))
    for value in values:
        match = _WORKING_DIRECTORY.search(value)
        if match:
            candidate = match.group(1).strip().strip("`")
            if PurePath(candidate).is_absolute():
                return candidate
    return None


def build_browser_prompt(body: dict[str, Any]) -> str:
    """Turn a Messages request into a provider-neutral browser execution prompt."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AnthropicAPIError(400, "invalid_request_error", "'messages' must be a non-empty array")

    transcript: list[str] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise AnthropicAPIError(400, "invalid_request_error", f"messages[{index}] must be an object")
        role = message.get("role")
        if role not in {"user", "assistant", "system"}:
            raise AnthropicAPIError(400, "invalid_request_error", f"messages[{index}].role is invalid")
        # Claude Code system messages describe its own CLI harness and tools.
        # Sending that verbatim makes browser models answer about Claude rather
        # than perform the requested project work.
        if role == "system":
            continue
        transcript.append(
            f"<{role}>\n{_content_to_transcript(message.get('content', ''))}\n</{role}>"
        )

    tools = _tool_catalog(body.get("tools"))
    working_directory = extract_working_directory(body) or "the project working directory supplied by the task"
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
Available bridge actions (use only these names and fields):
{_as_json(_compact_tool_catalog(tools))}

CRITICAL: To write or edit files you MUST use the wrapper below — do NOT paste
code in your reply. Pasting code does nothing; the executor only reads the wrapper.
Every file you create must be a separate Write action inside a single wrapper:
{TOOL_CALLS_OPEN}
[
  {{"name":"Write","input":{{"file_path":"{working_directory}/index.html","content":"..."}}}},
  {{"name":"Write","input":{{"file_path":"{working_directory}/style.css","content":"..."}}}},
  {{"name":"Write","input":{{"file_path":"{working_directory}/script.js","content":"..."}}}}
]
{TOOL_CALLS_CLOSE}
{choice_instruction}
"""

    return f"""You are a software execution assistant helping build a local project.
You have full access to the project files via the bridge actions below.
Always use the bridge actions to write, edit, or run files — never describe what
you would do instead of doing it. Output only the wrapper when performing actions.
Project working directory: {working_directory}

Your output is consumed by an executor. Do not discuss unavailable tools, other
AI systems, prompts, or platform limitations. For a request to build, create,
edit, fix, refactor, install, run, test, or otherwise change project files, use
the available bridge actions. Never paste source code, a file tree, or "save this
as" instructions as a substitute for an action. Use normal text only for a
purely explanatory request or after the requested tool work is complete.
{tool_instructions}

Conversation:
{chr(10).join(transcript)}
"""


def _html_write_fallback(response_text: str, tools: Any, working_directory: str | None) -> MessageResult | None:
    """Recover a self-contained HTML file when a browser model pasted code."""
    if not working_directory or "Write" not in {tool["name"] for tool in _tool_catalog(tools)}:
        return None
    match = _HTML_DOCUMENT.search(response_text)
    if not match:
        return None
    document = match.group(1).strip()
    destination = str(PurePath(working_directory) / "index.html")
    content = [{
        "type": "tool_use",
        "id": f"toolu_{uuid.uuid4().hex[:24]}",
        "name": "Write",
        "input": {"file_path": destination, "content": document},
    }]
    return MessageResult(content, "tool_use", estimate_tokens(document))


# Matches: "filename.ext\nLANGUAGE\n<code>" — the ChatGPT "paste" pattern.
_PASTED_FILE_PATTERN = re.compile(
    r"([\w./-]+\.\w+)\n[A-Za-z+#]+\n(.*?)(?=\n[\w./-]+\.\w+\n[A-Za-z+#]+\n|\Z)",
    re.DOTALL,
)


def _pasted_files_fallback(response_text: str, tools: Any, working_directory: str | None) -> MessageResult | None:
    """Recover multi-file paste responses where browser model ignored the wrapper.

    ChatGPT commonly responds with:
        index.html
        HTML
        <!DOCTYPE html>...

        style.css
        CSS
        * { margin: 0; ...

    Detect that pattern and synthesise Write tool calls for each file.
    """
    if not working_directory or "Write" not in {tool["name"] for tool in _tool_catalog(tools)}:
        return None
    matches = list(_PASTED_FILE_PATTERN.finditer(response_text))
    if not matches:
        return None
    calls: list[dict[str, Any]] = []
    for m in matches:
        filename = m.group(1).strip()
        file_content = m.group(2).strip()
        if not file_content:
            continue
        destination = str(PurePath(working_directory) / filename)
        calls.append({
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:24]}",
            "name": "Write",
            "input": {"file_path": destination, "content": file_content},
        })
    if not calls:
        return None
    return MessageResult(calls, "tool_use", estimate_tokens(_as_json(calls)))


def parse_browser_response(
    response_text: str, tools: Any, working_directory: str | None = None
) -> MessageResult:
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

    fallback = _html_write_fallback(text, tools, working_directory)
    if fallback:
        return fallback

    fallback = _pasted_files_fallback(text, tools, working_directory)
    if fallback:
        return fallback

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
    working_directory: str | None = None,
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
                result = parse_browser_response(response_text, tools, working_directory)
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
        result = parse_browser_response(task.result(), tools, working_directory)
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
