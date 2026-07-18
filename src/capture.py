"""Opt-in, local request/response capture for API traffic."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CAPTURE_FILE = re.compile(r"^(\d{6})\.json$")
_LOCK = threading.Lock()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".capture-", suffix=".json", delete=False
    ) as temporary:
        json.dump(value, temporary, indent=2, ensure_ascii=False, default=str)
        temporary.write("\n")
        temporary_path = temporary.name
    os.replace(temporary_path, path)


def _next_path(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    highest = 0
    for file in directory.iterdir():
        match = _CAPTURE_FILE.match(file.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return directory / f"{highest + 1:06d}.json"


@dataclass
class ExchangeCapture:
    """A single request whose file is updated once its response is known."""

    path: Path
    payload: dict[str, Any]

    @classmethod
    def start(
        cls,
        directory: str,
        request: dict[str, Any],
        *,
        endpoint: str | None = None,
        processed_request: str | None = None,
    ) -> "ExchangeCapture":
        with _LOCK:
            path = _next_path(Path(directory))
            payload = {
                "id": path.stem,
                "received_at": _timestamp(),
                "endpoint": endpoint,
                "request": request,
                "processed_request": processed_request,
                "browser_response": None,
                "api_response": None,
                "error": None,
                "completed_at": None,
            }
            _atomic_json_write(path, payload)
        return cls(path, payload)

    def complete(self, *, browser_response: str, api_response: dict[str, Any]) -> None:
        self.payload.update({
            "browser_response": browser_response,
            "api_response": api_response,
            "completed_at": _timestamp(),
        })
        _atomic_json_write(self.path, self.payload)

    def fail(self, message: str) -> None:
        self.payload.update({"error": message, "completed_at": _timestamp()})
        _atomic_json_write(self.path, self.payload)
