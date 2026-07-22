"""Hermes plugin that gives Davie an explicit local StackChan body."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from stackchan_client import StackChanClient, StackChanConfig, StackChanError, json_result


STATUS_SCHEMA = {
    "name": "stackchan_status",
    "description": (
        "Check Davie's local StackChan body, current device-session readiness, and available "
        "voice/vision/reader/control capabilities. Use this before saying the robot cannot help, "
        "and before immediate speech, camera, or device-control actions. This is a zero-model local check."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "include_capabilities": {
                "type": "boolean",
                "description": "Include the short capability list. Defaults to true.",
            }
        },
    },
}


def _config() -> StackChanConfig:
    return StackChanConfig.load()


def _available() -> bool:
    try:
        return _config().enabled
    except StackChanError:
        return False


def _handle_status(args: dict[str, Any], **_kwargs: Any) -> str:
    include = args.get("include_capabilities", True)
    return json_result(
        StackChanClient(_config()).status,
        include_capabilities=include if isinstance(include, bool) else True,
    )


def _command_status(_raw_args: str = "") -> str:
    try:
        payload = StackChanClient(_config()).status(include_capabilities=False)
    except StackChanError as exc:
        payload = exc.as_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="stackchan_status",
        toolset="stackchan",
        schema=STATUS_SCHEMA,
        handler=_handle_status,
        check_fn=_available,
        description=STATUS_SCHEMA["description"],
        emoji="🤖",
    )
    try:
        ctx.register_command(
            "stackchan",
            _command_status,
            description="Show local StackChan gateway and device-session status.",
            args_hint="(no args)",
        )
    except Exception:
        pass

