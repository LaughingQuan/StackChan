"""Hermes plugin that gives Davie an explicit local StackChan body."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from stackchan_client import StackChanClient, StackChanConfig, StackChanError, json_result


_CURRENT_STATE_ENTITY_RE = re.compile(
    r"(?:stack[\s-]?chan|desktop\s+robot|desk\s+robot|"
    r"davie(?:'s|\s+的)?\s*(?:robot|body|机器人|身体)|桌面机器人|机器人\s*davie)",
    re.IGNORECASE,
)
_CURRENT_STATE_REQUEST_RE = re.compile(
    r"(?:"
    r"现在|当前|目前|此刻|状态|在线|离线|连接|可用|能用|正常|"
    r"醒着|唤醒|叫不醒|在听|黑屏|屏幕.{0,4}(?:黑|暗)|物理会话|"
    r"current|now|status|online|offline|connect(?:ed|ion)?|available|"
    r"usable|ready|awake|listening|wake|dark\s+screen|physical\s+session"
    r")",
    re.IGNORECASE,
)


STATUS_SCHEMA = {
    "name": "stackchan_status",
    "description": (
        "MANDATORY live-state check before saying Davie's StackChan body is currently connected, "
        "ready, awake, listening, available, offline, or usable now. Knowledge/RAG only describes "
        "capabilities and history; it never proves current physical state. Gateway health alone also "
        "does not prove an active robot session. Use this before immediate speech, camera, or device "
        "control actions. This is a zero-model local check."
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

READER_SCHEMA = {
    "name": "stackchan_reader",
    "description": (
        "Prepare and control Davie's resumable StackChan reading mode. Use load with extracted plain "
        "text, or a local UTF-8 TXT/Markdown/HTML source_path. Other document formats must go through "
        "Davie Document Intake first. Content may be loaded while the robot is offline; play/pause/resume "
        "need the user to wake StackChan by saying 'Davie'. Resume repeats an interrupted current sentence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["load", "status", "play", "pause", "resume", "stop", "clear"],
            },
            "title": {"type": "string", "description": "Title used when action=load."},
            "text": {
                "type": "string",
                "description": "Extracted reading text. Do not provide together with source_path.",
            },
            "source_path": {
                "type": "string",
                "description": "Absolute or home-relative UTF-8 TXT/Markdown/HTML path in an allowed document root.",
            },
            "autoplay": {
                "type": "boolean",
                "description": "Start immediately after load; requires an awake device. Defaults to false.",
            },
        },
        "required": ["action"],
    },
}

CONTROL_SCHEMA = {
    "name": "stackchan_control",
    "description": (
        "Control only the allow-listed physical functions of Davie's local StackChan body: speaker "
        "volume, head angles, onboard LED RGB, or ending the current voice session. The robot must "
        "be awake. Do not use this for room lights or unrelated devices, and do not invent MCP tool names."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["volume", "head", "led", "sleep"]},
            "volume": {"type": "integer", "minimum": 0, "maximum": 100},
            "yaw": {
                "type": "integer",
                "minimum": -128,
                "maximum": 128,
                "description": "Horizontal degrees; negative is StackChan's left. Prefer +/-45 for natural motion.",
            },
            "pitch": {"type": "integer", "minimum": 0, "maximum": 90},
            "speed": {"type": "integer", "minimum": 100, "maximum": 1000, "description": "150 is natural."},
            "red": {"type": "integer", "minimum": 0, "maximum": 168},
            "green": {"type": "integer", "minimum": 0, "maximum": 168},
            "blue": {"type": "integer", "minimum": 0, "maximum": 168},
        },
        "required": ["action"],
    },
}

REMINDER_SCHEMA = {
    "name": "stackchan_reminder",
    "description": (
        "Create, list, or stop a short reminder stored and executed locally by an awake StackChan. "
        "This is a device-local convenience reminder while the robot remains powered, not a durable "
        "calendar or Hermes cron job. Use Hermes cron for persistent scheduled work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "stop"]},
            "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
            "message": {"type": "string", "description": "What StackChan should say when the reminder fires."},
            "repeat": {"type": "boolean", "description": "Repeat at the same interval. Defaults to false."},
            "reminder_id": {"type": "integer", "minimum": 0, "description": "Required for action=stop."},
        },
        "required": ["action"],
    },
}

STORAGE_SCHEMA = {
    "name": "stackchan_storage",
    "description": (
        "Use Davie's optional StackChan TF edge memory. This tool can check card health, run a "
        "tiny non-destructive self-test, save or read short local notes, read the mirrored book "
        "checkpoint, or inspect bounded device diagnostics. Use save_note when the user explicitly "
        "asks the desktop robot to remember a short item locally. This is not Knowledge Atlas and "
        "must not store credentials, raw audio, or long documents. The robot must be awake."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "self_test",
                    "save_note",
                    "recent_notes",
                    "reader_checkpoint",
                    "diagnostics",
                ],
            },
            "text": {
                "type": "string",
                "description": "Short plain-text note for save_note, at most 480 UTF-8 bytes.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Number of recent notes or diagnostics. Defaults to 3.",
            },
        },
        "required": ["action"],
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


def _handle_reader(args: dict[str, Any], **_kwargs: Any) -> str:
    autoplay = args.get("autoplay", False)
    return json_result(
        StackChanClient(_config()).reader,
        str(args.get("action") or ""),
        title=str(args.get("title") or ""),
        text=str(args.get("text") or ""),
        source_path=str(args.get("source_path") or ""),
        autoplay=autoplay if isinstance(autoplay, bool) else False,
    )


def _handle_control(args: dict[str, Any], **_kwargs: Any) -> str:
    return json_result(
        StackChanClient(_config()).control,
        str(args.get("action") or ""),
        volume=args.get("volume"),
        yaw=args.get("yaw"),
        pitch=args.get("pitch"),
        speed=args.get("speed", 150),
        red=args.get("red"),
        green=args.get("green"),
        blue=args.get("blue"),
    )


def _handle_reminder(args: dict[str, Any], **_kwargs: Any) -> str:
    return json_result(
        StackChanClient(_config()).reminder,
        str(args.get("action") or ""),
        duration_seconds=args.get("duration_seconds"),
        message=str(args.get("message") or ""),
        repeat=args.get("repeat", False),
        reminder_id=args.get("reminder_id"),
    )

def _handle_storage(args: dict[str, Any], **_kwargs: Any) -> str:
    return json_result(
        StackChanClient(_config()).storage,
        str(args.get("action") or ""),
        text=str(args.get("text") or ""),
        limit=args.get("limit", 3),
    )


def _command_status(_raw_args: str = "") -> str:
    try:
        payload = StackChanClient(_config()).status(include_capabilities=False)
    except StackChanError as exc:
        payload = exc.as_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_live_state_response(evidence: dict[str, Any], *, chinese: bool) -> str:
    gateway_reachable = evidence.get("gateway_reachable") is True
    live_state = evidence.get("live_state")
    if not isinstance(live_state, dict):
        live_state = {}
    physical_status = str(live_state.get("physical_status") or "unknown")

    if chinese:
        gateway_line = "可达" if gateway_reachable else "当前查询失败"
        if physical_status == "active_session":
            session_line = "已有活动物理会话，可以接收即时说话、摄像头和设备控制请求。"
            next_step = "直接对 Davie 说需求即可；声学与触摸体验仍以真人实际操作为准。"
        elif physical_status == "no_active_session":
            session_line = (
                "当前没有活动物理会话。这不等于机器人断电或 Wi-Fi 离线，只表示它尚未进入 "
                "Davie 语音会话。"
            )
            next_step = (
                "在机器人旁说“Davie”，或点一下 Davie 的脸；看到 Listening... 后再说需求。"
            )
        else:
            session_line = "当前无法确认物理机器人是否已建立会话，不能据此声称在线或离线。"
            next_step = "先确认 Stack-chan 已开机联网，再说“Davie”或点一下脸建立会话。"
        return (
            "Stack-chan 实时状态\n"
            f"- 本地 Gateway：{gateway_line}\n"
            f"- 物理会话：{session_line}\n\n"
            "黑屏可能只是正常息屏，不能单独作为离线证据。\n"
            f"下一步：{next_step}"
        )

    gateway_line = "reachable" if gateway_reachable else "live query failed"
    if physical_status == "active_session":
        session_line = (
            "An active physical session is connected and can accept immediate speech, camera, "
            "and device-control requests."
        )
        next_step = (
            "Speak your request directly; acoustic and touch quality still require real human use."
        )
    elif physical_status == "no_active_session":
        session_line = (
            "There is no active physical session. This does not prove that the robot is powered "
            "off or disconnected from Wi-Fi; it only means it has not entered a Davie voice session."
        )
        next_step = (
            'Say "Davie" near the robot, or tap Davie\'s face once, then wait for Listening...'
        )
    else:
        session_line = (
            "The current physical session cannot be confirmed, so the robot must not be reported "
            "as online or offline."
        )
        next_step = (
            'Confirm that Stack-chan is powered and networked, then say "Davie" or tap its face.'
        )
    return (
        "Stack-chan live status\n"
        f"- Local Gateway: {gateway_line}\n"
        f"- Physical session: {session_line}\n\n"
        "A dark screen may be normal display sleep and is not, by itself, offline evidence.\n"
        f"Next step: {next_step}"
    )


def _live_state_evidence() -> dict[str, Any]:
    try:
        return StackChanClient(_config()).status(include_capabilities=False)
    except StackChanError as exc:
        return exc.as_dict()


def _send_gateway_text(gateway: Any, event: Any, text: str) -> bool:
    source = getattr(event, "source", None)
    if source is None:
        return False
    adapter = getattr(gateway, "adapters", {}).get(getattr(source, "platform", None))
    chat_id = getattr(source, "chat_id", None)
    if adapter is None or not hasattr(adapter, "send") or not chat_id:
        return False
    try:
        asyncio.get_running_loop().create_task(adapter.send(chat_id, text))
        return True
    except Exception:
        return False


def _handle_current_state_pre_gateway_dispatch(**kwargs: Any) -> dict[str, str]:
    event = kwargs.get("event")
    gateway = kwargs.get("gateway")
    user_message = str(getattr(event, "text", "") or "").strip()
    if (
        not user_message
        or gateway is None
        or not _CURRENT_STATE_ENTITY_RE.search(user_message)
        or not _CURRENT_STATE_REQUEST_RE.search(user_message)
    ):
        return {"action": "allow"}

    evidence = _live_state_evidence()
    response = _format_live_state_response(
        evidence,
        chinese=bool(re.search(r"[\u3400-\u9fff]", user_message)),
    )
    if _send_gateway_text(gateway, event, response):
        return {"action": "skip", "reason": "stackchan_live_state_sent"}
    return {"action": "allow"}


def stackchan_pre_llm_hint(**kwargs: Any) -> dict[str, str] | None:
    """Inject current physical-state evidence when the user explicitly asks for it."""
    user_message = str(kwargs.get("user_message") or "").strip()
    if (
        not user_message
        or not _CURRENT_STATE_ENTITY_RE.search(user_message)
        or not _CURRENT_STATE_REQUEST_RE.search(user_message)
    ):
        return None

    evidence = _live_state_evidence()
    exact_response = _format_live_state_response(
        evidence,
        chinese=bool(re.search(r"[\u3400-\u9fff]", user_message)),
    )

    compact_evidence = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "context": (
            "[StackChan current-state evidence]\n"
            "A live local StackChan status query for this exact turn has already completed. "
            "Return the exact prepared answer below and stop. Do not call any tool, inspect the "
            "host display, ask what StackChan means, invent Docker/container/monitoring checks, "
            "or call stackchan_status again. "
            "Distinguish Gateway reachability from an active physical device session. "
            "A dark screen may be normal display sleep and is not proof that the robot is offline. "
            "The screen-tap fallback is loaded in firmware, but its physical acceptance remains "
            "pending_human until a person confirms the real touch interaction. Never describe "
            "wake-word, touch, speaker, or microphone behavior as human-verified unless the "
            "evidence explicitly says so.\n"
            f"Exact prepared answer:\n{exact_response}\n"
            f"Live evidence JSON: {compact_evidence}"
        )
    }


def register(ctx: Any) -> None:
    for schema, handler, emoji in (
        (STATUS_SCHEMA, _handle_status, "🤖"),
        (SAY_SCHEMA, _handle_say, "🔊"),
        (VISION_SCHEMA, _handle_vision, "👁"),
        (READER_SCHEMA, _handle_reader, "📖"),
        (CONTROL_SCHEMA, _handle_control, "🎛"),
        (REMINDER_SCHEMA, _handle_reminder, "⏰"),
        (STORAGE_SCHEMA, _handle_storage, "💾"),
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
        ctx.register_hook("pre_llm_call", stackchan_pre_llm_hint)
    except (AttributeError, TypeError):
        pass
    try:
        ctx.register_hook(
            "pre_gateway_dispatch",
            _handle_current_state_pre_gateway_dispatch,
        )
    except (AttributeError, TypeError):
        pass
    try:
        ctx.register_command(
            "stackchan",
            _command_status,
            description="Show local StackChan gateway and device-session status.",
            args_hint="(no args)",
        )
    except Exception:
        pass
