# StackChan Davie Integration Loop

## Run Contract

```yaml
project: "StackChan Davie local runtime (repository root)"
scope: "Integrate the official StackChan firmware with a local Davie gateway while preserving upstream audio, camera, motion, provisioning, OTA, and recovery behavior."
autonomy_level: "bounded"
boundaries:
  - "No paid or cloud model/API calls; money budget is zero."
  - "Do not modify Davie executor/proactivity core or unrelated Hermes services."
  - "Never commit or print Wi-Fi credentials, tokens, account secrets, or private device identifiers."
  - "Preserve the verified factory 1.4.4 full-flash backup and a documented restore path."
  - "Do not format or depend on the current 32 GB TF card."
  - "Do not flash hardware until the official host tests, full ESP-IDF build, gateway tests, secret scan, and partition compatibility check pass."
  - "Do not claim wake-word, acoustic interruption, camera, motion, or playback success without physical evidence."
stop:
  - "A required hardware or product decision cannot be resolved without the user."
  - "Two consecutive loops produce no verified improvement."
  - "All staged acceptance checks pass and the integration report is complete."
budget:
  money: 0
verify:
  zero_cost:
    - "Official firmware host tests exit 0."
    - "Official firmware full ESP-IDF build exits 0."
    - "Davie gateway unit and protocol-contract tests exit 0."
    - "No credentials or secrets are present in tracked files."
    - "Generated partition table is compatible with the backed-up device layout before flashing."
    - "Git diff and status contain only intentional project-scoped changes."
paid_allowed_after_zero_cost: false
comms_log: "STACKCHAN_DAVIE_LOOP.md"
progress_log: "STACKCHAN_DAVIE_LOOP.md"
handoff:
  - "Report completed stages, exact test evidence, physical checks still pending, commit IDs, and rollback instructions."
```

## Claims

### 【已关闭】Codex 2026-07-23 02:30 Asia/Singapore — official firmware, local gateway, and physical acceptance
- 改动: firmware/main/CMakeLists.txt, firmware/sdkconfig.defaults.davie.example, integrations/davie-gateway/**, STACKCHAN_DAVIE_LOOP.md, project documentation
- 结果: official 1.4.3 Davie integration verified and deployed; human close-range acoustic wake/interruption remains an explicit physical acceptance item
- 边界: no paid API, no credential output/commit, factory backup and NVS preserved, no TF-card dependency, no unrelated Davie changes

## Dependency Requests

- None. Wi-Fi provisioning information was supplied out of band and must remain outside tracked files.

## Completions

- Architecture decision recorded: official 1.4.3 source fork plus a decoupled local protocol adapter.
- Factory 1.4.4 full-flash recovery image exists on NAS and has a recorded SHA-256 digest.
- Official host test suite passed before integration changes.


### 【完成】Codex 2026-07-23 03:05 Asia/Singapore — official StackChan 1.4.3 Davie local runtime
- 发现: stock firmware already provided the required camera, duplex audio, motion, OTA, MCP, provisioning, and AI Agent lifecycle; the narrowest maintainable design was an upstream-first build flag plus a decoupled Xiaozhi/Davie gateway. A live vision-follow-up bug was also found: camera requests used a stable memory key instead of the active spoken session.
- 修复: added the `CONFIG_STACKCHAN_DAVIE_LOCAL_RUNTIME` build profile, official MultiNet5 English `Davie` wake command, device AEC, size-safe official assets, and the standalone `integrations/davie-gateway`. Camera analysis now resolves the active device/client voice session and propagates its Davie session ID so spoken follow-ups retain visual context.
- 验证: official host test 1/1 passed; full ESP-IDF reconfigure/build passed; gateway `uv run pytest -q` 24 passed; compileall passed; wheel/sdist build passed; generated partition table exactly matched the physical device; flash hashes matched; boot confirmed 1.4.3, camera, touch, RTC, IMU, servos, MCP, duplex audio, Wi-Fi, local OTA, MultiNet5 Q8 and `Davie`; production gateway health/auth/systemd checks passed; voice E2E returned STT/LLM/TTS and 253,440 PCM bytes; vision E2E accurately described the test image; source and installed package hashes matched.
- 花费: ¥0; no paid or cloud model/API action was used.
- 边界: credentials remain only in ignored/local device configuration; NVS and recovery images were preserved; TF card is optional; no Davie executor/proactivity or unrelated Hermes service was changed.
- 后续: perform one human close-range `Davie` wake test and one audible playback interruption test beside the device. These two acoustic checks are intentionally not inferred from synthetic playback or boot logs.

## Verification Ledger

| Stage | Check | Status | Evidence |
| --- | --- | --- | --- |
| Baseline | Official host tests | passed | `motion_math_test`, 1/1 tests passed |
| Baseline | Full ESP-IDF build | passed | `idf.py reconfigure build`; app `0x39c5e0`, 27% free |
| Gateway | Protocol and behavior tests | passed | `uv run pytest -q`: 24 passed; compileall and wheel/sdist build passed |
| Firmware | Partition compatibility | passed | Generated table exactly matches physical partition layout |
| Device | Wi-Fi and local gateway | passed | Retained NVS, joined 2.4 GHz Wi-Fi, local OTA `:8793` healthy |
| Device | Boot, audio, camera, menu, motion | passed | 1.4.3 boot; duplex audio/AEC path; GC0308; touch/RTC/IMU/servos/MCP tools initialized |
| Device | Wake model load | passed | Official MultiNet5 English Q8 loaded with command/display `Davie` |
| Device | Human acoustic wake/interruption | pending-human | Requires a person beside the device; synthetic Mac playback is not accepted as evidence |
| Gateway | Live voice E2E | passed | hello/llm/stt/tts events; 253,440 PCM bytes returned |
| Gateway | Live vision and session continuity | passed | Real image analyzed; camera response reuses active spoken Davie session |
| Recovery | Factory and pre-Davie backup | passed | NAS full-flash/NVS images and SHA-256 manifests verified; restore commands documented |
| Repository | Intent and credential audit | passed | Staged diff contains only intentional project files; secrets, Wi-Fi config, runtime env, build output, and private LAN defaults are excluded |
