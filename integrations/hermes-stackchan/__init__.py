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

SAY_SCHEMA = {
    "name": "stackchan_say",
    "description": (
        "Speak a short message through Davie's local StackChan body. Use only when the user asks "
        "Davie to say, announce, or read a short result aloud through the robot, or when an already "
        "approved local workflow requires that output. The robot must first be awake in a Davie session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Plain spoken text, at most 1000 characters; avoid Markdown and URLs.",
            }
        },
        "required": ["text"],
    },
}

VISION_SCHEMA = {
    "name": "stackchan_vision",
    "description": (
        "Ask Davie's local StackChan camera to inspect and explain the scene in front of the robot. "
        "Use when the user explicitly refers to what StackChan can see or asks the robot to inspect "
        "an object. The robot must be awake. Set speak=false when the result should stay in chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Specific visual question, at most 500 characters.",
            },
            "speak": {
                "type": "boolean",
                "description": "Whether StackChan should also say the visual answer aloud. Defaults to true.",
            },
        },
        "required": ["question"],
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


def _handle_say(args: dict[str, Any], **_kwargs: Any) -> str:
    return json_result(StackChanClient(_config()).say, str(args.get("text") or ""))


def _handle_vision(args: dict[str, Any], **_kwargs: Any) -> str:
    speak = args.get("speak", True)
    return json_result(
        StackChanClient(_config()).vision,
        str(args.get("question") or ""),
        speak=speak if isinstance(speak, bool) else True,
    )


def _command_status(_raw_args: str = "") -> str:
    try:
        payload = StackChanClient(_config()).status(include_capabilities=False)
    except StackChanError as exc:
        payload = exc.as_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def register(ctx: Any) -> None:
    for schema, handler, emoji in (
        (STATUS_SCHEMA, _handle_status, "🤖"),
        (SAY_SCHEMA, _handle_say, "🔊"),
        (VISION_SCHEMA, _handle_vision, "👁"),
    ):
        ctx.register_tool(
            name=schema["name"],
            toolset="stackchan",
            schema=schema,
            handler=handler,
            check_fn=_available,
            description=schema["description"],
            emoji=emoji,
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
