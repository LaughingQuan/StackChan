# Davie StackChan Hermes Plugin

`jm-stackchan` gives Davie seven explicit local tools without changing Hermes core:

- `stackchan_status`
- `stackchan_say`
- `stackchan_vision`
- `stackchan_reader`
- `stackchan_control`
- `stackchan_reminder`
- `stackchan_storage`

The plugin calls the authenticated StackChan gateway. It never embeds a token in source or
`config.yaml`; configuration only points to a local mode-`0600` token file.

When a user explicitly asks whether the desktop robot is currently online, awake, connected,
usable, or showing a dark screen, a narrow `pre_llm_call` hook fetches authenticated live-state
evidence before inference. Unrelated turns do not perform this query. The hook distinguishes
Gateway reachability from an active physical device session and preserves `pending_human` for
touch, wake-word, microphone, and speaker acceptance.

Messaging Gateway channels such as Telegram and Feishu use the same evidence to return a short
deterministic status answer before model dispatch. This avoids slow or invented host checks for
a question that has a single authenticated local answer. API/CLI turns receive the prepared
answer through `pre_llm_call` without changing Hermes core.

## Install

```bash
python install.py \
  --base-url http://stackchan-gateway.local:8793 \
  --admin-token-file ~/.hermes/secrets/stackchan-admin-token \
  --default-device-id '<device identity>'

cd ~/.hermes/hermes-agent
uv run hermes plugins enable jm-stackchan
```

The official plugin command adds the `stackchan` toolset to the configured Hermes platforms.
Immediate speech, camera, playback, and controls require StackChan to be awake in a Davie session.
Reader content can be preloaded while the device is offline.
Davie can end the active session with `stackchan_control(action="sleep")`; the
same lifecycle is available by voice with `Goodbye Davie` or `休息吧`.
