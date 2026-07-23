from __future__ import annotations

from stackchan_davie_gateway.capabilities import capability_manifest, parse_device_action


def test_capability_manifest_is_voice_first_and_names_wake_word() -> None:
    manifest = capability_manifest()
    assert manifest["assistant"] == "Davie"
    assert manifest["wake_word"] == "Davie"
    assert manifest["interaction"] == "voice_first"
    assert manifest["voice_session"] == {
        "wake": {
            "method": "device_local_voice",
            "phrase": "Davie",
            "instruction": (
                "Say 'Davie' near the device, then wait for the screen to show Listening. "
                "If speech is missed, tap Davie's face once."
            ),
            "fallback": {
                "method": "screen_tap",
                "target": "avatar_face",
                "instruction": (
                    "Tap Davie's face once to start or end a voice session if the wake phrase "
                    "is missed."
                ),
            },
        },
        "end": {
            "voice_phrases": ["Goodbye Davie", "Go to sleep", "休息吧"],
            "tool": {"name": "stackchan_control", "arguments": {"action": "sleep"}},
        },
        "idle_timeout_seconds": 120,
        "remote_wake_supported": False,
    }
    assert {item["id"] for item in manifest["capabilities"]} >= {
        "vision",
        "reader",
        "edge_memory",
        "reminder",
        "session_control",
    }
    assert manifest["voice_session"]["wake"]["fallback"]["method"] == "screen_tap"


def test_parse_reader_and_device_actions_in_both_languages() -> None:
    assert parse_device_action("Davie, what can you do?").kind == "help"
    assert parse_device_action("Davie, continue reading.").kind == "reader_resume"
    assert parse_device_action("暂停朗读").kind == "reader_pause"
    assert parse_device_action("set the volume to 45").arguments == {"volume": 45}
    assert parse_device_action("把头转向左边").arguments == {"direction": "left"}
    assert parse_device_action("set the LED to blue").arguments == {"color": "blue"}
    assert parse_device_action("Davie, go to sleep.").kind == "session_sleep"
    assert parse_device_action("休息吧").kind == "session_sleep"
    saved = parse_device_action("Davie, remember this: call the bank on Friday")
    assert saved is not None
    assert saved.kind == "storage_note_save"
    assert saved.arguments == {"text": "call the bank on Friday"}
    assert parse_device_action("记一下，周五给母行回复").kind == "storage_note_save"
    assert parse_device_action("Davie, read my saved notes").kind == "storage_notes_recent"
    assert parse_device_action("查看TF卡状态").kind == "storage_status"


def test_parse_reminder_converts_units_and_rejects_out_of_range() -> None:
    reminder = parse_device_action("Remind me in 10 minutes to take a break")
    assert reminder is not None
    assert reminder.kind == "reminder"
    assert reminder.arguments == {
        "duration_seconds": 600,
        "message": "take a break",
        "repeat": False,
    }
    chinese = parse_device_action("2小时后提醒我开会")
    assert chinese is not None
    assert chinese.arguments["duration_seconds"] == 7200
    assert parse_device_action("remind me in 25 hours to stop") is None


def test_general_conversation_is_not_misclassified_as_device_control() -> None:
    assert parse_device_action("I stopped reading that book last year.") is None
    assert parse_device_action("Look at this photo and explain it.") is None
    assert parse_device_action("What do you think about blue light?") is None
    assert parse_device_action("Do you remember our last conversation?") is None
