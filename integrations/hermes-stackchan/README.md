# Davie StackChan Hermes Plugin

`jm-stackchan` gives Davie six explicit local tools without changing Hermes core:

- `stackchan_status`
- `stackchan_say`
- `stackchan_vision`
- `stackchan_reader`
- `stackchan_control`
- `stackchan_reminder`

The plugin calls the authenticated StackChan gateway. It never embeds a token in source or
`config.yaml`; configuration only points to a local mode-`0600` token file.

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

