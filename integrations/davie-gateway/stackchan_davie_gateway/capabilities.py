from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "id": "conversation",
        "label": "Talk with Davie",
        "description": "Ask questions and continue the same Davie conversation by voice.",
    },
    {
        "id": "vision",
        "label": "Look and explain",
        "description": "Use the camera to explain an object, text, or scene in front of StackChan.",
    },
    {
        "id": "reader",
        "label": "Read aloud",
        "description": "Read a loaded book or article, then pause, continue, or stop by voice.",
    },
    {
        "id": "reminder",
        "label": "Set a reminder",
        "description": "Create a short local reminder on StackChan.",
    },
    {
        "id": "device_control",
        "label": "Control StackChan",
        "description": "Adjust volume, head direction, and onboard LED color.",
    },
    {
        "id": "remote_output",
        "label": "Davie output endpoint",
        "description": "Let Davie speak or use the camera through authenticated gateway APIs.",
    },
)


@dataclass(frozen=True)
class DeviceAction:
    kind: str
    arguments: dict[str, Any] = field(default_factory=dict)
    chinese: bool = False


_HELP = re.compile(
    r"(?:what can you do|show (?:me )?(?:the )?(?:menu|commands)|help menu|"
    r"你能做什么|你会做什么|功能菜单|帮助菜单)",
    re.IGNORECASE,
)
_READER_PAUSE = re.compile(
    r"(?:pause (?:the )?(?:book|reading)|stop reading for now|暂停(?:朗读|阅读)|先别读了)",
    re.IGNORECASE,
)
_READER_RESUME = re.compile(
    r"(?:continue (?:the )?(?:book|reading)|resume (?:the )?(?:book|reading)|"
    r"keep reading|继续(?:朗读|阅读)|接着读)",
    re.IGNORECASE,
)
_READER_STOP = re.compile(
    r"(?:stop (?:the )?(?:book|reading)|end (?:the )?reading|停止(?:朗读|阅读)|结束朗读)",
    re.IGNORECASE,
)
_READER_STATUS = re.compile(
    r"(?:reading status|where (?:are we|did we stop)(?: in the book)?|"
    r"读到哪里了|阅读进度|朗读进度)",
    re.IGNORECASE,
)
_REMINDER_EN = re.compile(
    r"\bremind me in\s+(\d{1,5})\s*(seconds?|minutes?|hours?)\s+(?:to\s+)?(.+)",
    re.IGNORECASE,
)
_REMINDER_ZH = re.compile(r"(\d{1,5})\s*(秒|分钟|小时)后提醒我\s*(.+)")
_VOLUME = re.compile(
    r"(?:set|change|turn)?\s*(?:the\s+)?volume\s*(?:to|at)?\s*(\d{1,3})|"
    r"(?:把)?音量(?:调到|设置为|设为)?\s*(\d{1,3})",
    re.IGNORECASE,
)
_HEAD = re.compile(
    r"(?:turn|move)\s+(?:your\s+)?head\s+(left|right|up|center)|"
    r"(?:把)?头(?:转向|转到|抬到)?\s*(左边|右边|上面|中间|正中)",
    re.IGNORECASE,
)
_LED = re.compile(
    r"(?:set|change|turn)?\s*(?:the\s+)?(?:onboard\s+)?led\s*(?:to)?\s*"
    r"(red|green|blue|white|off)|"
    r"(?:把)?(?:机身)?灯(?:设置|设|调)?(?:成|为)?\s*(红色|绿色|蓝色|白色|关闭)",
    re.IGNORECASE,
)


def capability_manifest() -> dict[str, Any]:
    return {
        "assistant": "Davie",
        "interaction": "voice_first",
        "wake_word": "Davie",
        "screen_menu": "official_launcher",
        "capabilities": list(CAPABILITIES),
        "example_voice_commands": [
            "Davie, what can you do?",
            "Davie, what do you see?",
            "Davie, continue reading.",
            "Davie, pause reading.",
            "Davie, remind me in ten minutes to take a break.",
            "Davie, set the volume to 45.",
        ],
    }


def capability_reply(*, chinese: bool) -> str:
    if chinese:
        return (
            "我可以和你对话、用摄像头看并解释、朗读文章或书籍并暂停继续，"
            "也可以设置提醒、调整音量和控制头部或灯光。你可以直接说，Davie，帮我看看这个。"
        )
    return (
        "I can talk with you, look and explain with my camera, read a book with pause and resume, "
        "set reminders, and control my volume, head, or light. Try saying, Davie, what do you see?"
    )


def parse_device_action(text: str) -> DeviceAction | None:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None
    chinese = bool(re.search(r"[\u3400-\u9fff]", normalized))

    if _HELP.search(normalized):
        return DeviceAction("help", chinese=chinese)
    if _READER_PAUSE.search(normalized):
        return DeviceAction("reader_pause", chinese=chinese)
    if _READER_RESUME.search(normalized):
        return DeviceAction("reader_resume", chinese=chinese)
    if _READER_STOP.search(normalized):
        return DeviceAction("reader_stop", chinese=chinese)
    if _READER_STATUS.search(normalized):
        return DeviceAction("reader_status", chinese=chinese)

    match = _REMINDER_EN.search(normalized)
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        multiplier = 1 if unit.startswith("second") else 60 if unit.startswith("minute") else 3600
        seconds = value * multiplier
        if 1 <= seconds <= 86400:
            return DeviceAction(
                "reminder",
                {"duration_seconds": seconds, "message": match.group(3).strip(), "repeat": False},
                chinese=False,
            )
    match = _REMINDER_ZH.search(normalized)
    if match:
        value = int(match.group(1))
        multiplier = {"秒": 1, "分钟": 60, "小时": 3600}[match.group(2)]
        seconds = value * multiplier
        if 1 <= seconds <= 86400:
            return DeviceAction(
                "reminder",
                {"duration_seconds": seconds, "message": match.group(3).strip(), "repeat": False},
                chinese=True,
            )

    match = _VOLUME.search(normalized)
    if match:
        volume = int(match.group(1) or match.group(2))
        if 0 <= volume <= 100:
            return DeviceAction("volume", {"volume": volume}, chinese=chinese)

    match = _HEAD.search(normalized)
    if match:
        direction = (match.group(1) or match.group(2)).lower()
        aliases = {"左边": "left", "右边": "right", "上面": "up", "中间": "center", "正中": "center"}
        return DeviceAction("head", {"direction": aliases.get(direction, direction)}, chinese=chinese)

    match = _LED.search(normalized)
    if match:
        color = (match.group(1) or match.group(2)).lower()
        aliases = {"红色": "red", "绿色": "green", "蓝色": "blue", "白色": "white", "关闭": "off"}
        return DeviceAction("led", {"color": aliases.get(color, color)}, chinese=chinese)

    return None
