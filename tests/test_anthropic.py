import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from src.anthropic import (
    TOOL_CALLS_CLOSE,
    TOOL_CALLS_OPEN,
    build_browser_prompt,
    parse_browser_response,
    stream_message,
)
from src.capture import ExchangeCapture
from src import chat


TOOLS = [{
    "name": "Bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


class AnthropicTranslationTests(unittest.TestCase):
    def test_preserves_tool_history_without_forwarding_cli_harness(self):
        prompt = build_browser_prompt({
            "system": [{"type": "text", "text": "You are a coding agent."}],
            "tools": TOOLS,
            "messages": [
                {"role": "assistant", "content": [{
                    "type": "tool_use", "id": "toolu_old", "name": "Bash", "input": {"command": "pwd"},
                }]},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": "toolu_old", "content": "/workspace",
                }]},
            ],
        })

        self.assertNotIn("You are a coding agent.", prompt)
        self.assertIn("You are an execution planner", prompt)
        self.assertIn("tool_use id=toolu_old name=Bash", prompt)
        self.assertIn("tool_result tool_use_id=toolu_old", prompt)
        self.assertIn('"name":"Bash"', prompt)
        self.assertIn(TOOL_CALLS_OPEN, prompt)
        self.assertIn("Available bridge actions", prompt)
        self.assertIn("Never paste source code", prompt)

    def test_recovers_self_contained_html_as_a_write_call(self):
        tools = TOOLS + [{
            "name": "Write",
            "input_schema": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["file_path", "content"],
            },
        }]
        response = "Here is the implementation:\n<!DOCTYPE html><html><body>Calculator</body></html>"
        result = parse_browser_response(response, tools, "/workspace/calculator")

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0]["name"], "Write")
        self.assertEqual(result.content[0]["input"]["file_path"], "/workspace/calculator/index.html")
        self.assertEqual(result.content[0]["input"]["content"], "<!DOCTYPE html><html><body>Calculator</body></html>")

    def test_converts_explicit_tool_wrapper_to_tool_use_block(self):
        response = f"{TOOL_CALLS_OPEN}\n[{{\"name\":\"Bash\",\"input\":{{\"command\":\"pwd\"}}}}]\n{TOOL_CALLS_CLOSE}"
        result = parse_browser_response(response, TOOLS)

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0]["type"], "tool_use")
        self.assertEqual(result.content[0]["name"], "Bash")
        self.assertEqual(result.content[0]["input"], {"command": "pwd"})
        self.assertTrue(result.content[0]["id"].startswith("toolu_"))

    def test_keeps_explanation_and_still_converts_embedded_tool_wrapper(self):
        response = (
            "This task needs a plan first.\n\n"
            f"{TOOL_CALLS_OPEN}\n[{{\"name\":\"Bash\",\"input\":{{\"command\":\"pwd\"}}}}]\n{TOOL_CALLS_CLOSE}"
        )
        result = parse_browser_response(response, TOOLS)

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0], {"type": "text", "text": "This task needs a plan first."})
        self.assertEqual(result.content[1]["type"], "tool_use")
        self.assertEqual(result.content[1]["name"], "Bash")

    def test_skips_an_invalid_example_wrapper_before_a_valid_tool_wrapper(self):
        response = (
            f"Example: {TOOL_CALLS_OPEN}\n[{{\"name\":\"tool\",\"input\":{{...}}}}]\n{TOOL_CALLS_CLOSE}\n"
            f"{TOOL_CALLS_OPEN}\n[{{\"name\":\"Bash\",\"input\":{{\"command\":\"pwd\"}}}}]\n{TOOL_CALLS_CLOSE}"
        )
        result = parse_browser_response(response, TOOLS)

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[-1]["name"], "Bash")

    def test_repairs_invalid_shell_backslash_escapes_in_tool_json(self):
        response = (
            f"{TOOL_CALLS_OPEN}\n"
            "[{\"name\":\"Bash\",\"input\":{\"command\":\"find . \\( -name package.json \\)\"}}]\n"
            f"{TOOL_CALLS_CLOSE}"
        )
        result = parse_browser_response(response, TOOLS)

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0]["input"], {"command": "find . \\( -name package.json \\)"})

    def test_invalid_tool_wrapper_is_returned_as_text(self):
        response = f"{TOOL_CALLS_OPEN}\n[{{\"name\":\"rm_everything\",\"input\":{{}}}}]\n{TOOL_CALLS_CLOSE}"
        result = parse_browser_response(response, TOOLS)

        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.content, [{"type": "text", "text": response}])


class AnthropicStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_starts_before_browser_result_and_uses_tool_events(self):
        started = asyncio.Event()

        async def fake_send_message(_prompt):
            started.set()
            await asyncio.sleep(0)
            return f"{TOOL_CALLS_OPEN}\n[{{\"name\":\"Bash\",\"input\":{{\"command\":\"pwd\"}}}}]\n{TOOL_CALLS_CLOSE}"

        events = []
        async for event in stream_message(
            prompt="hello", model="claude-sonnet-4-6", input_tokens=2,
            tools=TOOLS, send_message=fake_send_message,
        ):
            events.append(event)

        self.assertTrue(started.is_set())
        self.assertTrue(events[0].startswith("event: message_start"))
        self.assertTrue(any("input_json_delta" in event for event in events))
        self.assertTrue(events[-1].startswith("event: message_stop"))
        self.assertIn('\\"command\\":\\"pwd\\"', "".join(events))

    async def test_client_disconnect_marks_stream_capture_as_failed(self):
        started = asyncio.Event()
        errors = []

        async def fake_send_message(_prompt):
            started.set()
            await asyncio.Event().wait()

        async def on_error(message):
            errors.append(message)

        stream = stream_message(
            prompt="hello", model="claude-sonnet-4-6", input_tokens=2,
            tools=None, send_message=fake_send_message, on_error=on_error,
        )
        await anext(stream)  # message_start
        next_event = asyncio.create_task(anext(stream))
        await started.wait()
        next_event.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await next_event
        self.assertEqual(errors, ["Client disconnected before the response was complete."])


class ExchangeCaptureTests(unittest.TestCase):
    def test_each_exchange_has_its_own_complete_json_file(self):
        with tempfile.TemporaryDirectory() as directory:
            first = ExchangeCapture.start(directory, {"messages": [{"role": "user", "content": "first"}]})
            first.complete(
                browser_response="first browser response",
                api_response={"content": [{"type": "text", "text": "first API response"}]},
            )
            second = ExchangeCapture.start(
                directory,
                {"messages": [{"role": "user", "content": "second"}]},
                endpoint="/v1/chat/completions",
                processed_request="USER: second",
            )

            self.assertEqual(first.path.name, "000001.json")
            self.assertEqual(second.path.name, "000002.json")
            payload = json.loads(Path(first.path).read_text(encoding="utf-8"))
            self.assertEqual(payload["request"]["messages"][0]["content"], "first")
            self.assertEqual(payload["browser_response"], "first browser response")
            self.assertEqual(payload["api_response"]["content"][0]["text"], "first API response")
            self.assertIsNotNone(payload["completed_at"])
            self.assertEqual(json.loads(Path(second.path).read_text(encoding="utf-8"))["endpoint"], "/v1/chat/completions")
            self.assertEqual(json.loads(Path(second.path).read_text(encoding="utf-8"))["processed_request"], "USER: second")


class ChatQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_requests_wait_instead_of_failing(self):
        class Provider:
            name = "test"

            def __init__(self):
                self.first_started = asyncio.Event()
                self.allow_first = asyncio.Event()
                self.messages = []

            async def start_new_chat(self, _worker):
                pass

            async def type_message(self, _worker, message):
                self.messages.append(message)
                if message == "first":
                    self.first_started.set()

            async def click_send(self, _worker):
                pass

            async def wait_for_response(self, _worker):
                if self.messages[-1] == "first":
                    await self.allow_first.wait()

            async def scrape_response(self, _worker):
                return f"response for {self.messages[-1]}"

        provider = Provider()
        original_lock, original_provider, original_worker = chat._lock, chat._provider, chat.get_browser_worker
        chat._lock = asyncio.Lock()
        chat._provider = provider
        chat.get_browser_worker = lambda: object()
        try:
            first = asyncio.create_task(chat.send_message("first"))
            await provider.first_started.wait()
            second = asyncio.create_task(chat.send_message("second"))
            await asyncio.sleep(0)
            self.assertFalse(second.done())
            provider.allow_first.set()
            self.assertEqual(await first, "response for first")
            self.assertEqual(await second, "response for second")
        finally:
            chat._lock, chat._provider, chat.get_browser_worker = original_lock, original_provider, original_worker
