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

### 【进行中】Codex 2026-07-23 04:16 Asia/Singapore — Davie callable StackChan integration   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, integrations/davie-gateway/**（仅在合同缺口需要时）, docs/**, STACKCHAN_DAVIE_LOOP.md, /Users/jm2m/.hermes/plugins/jm-stackchan/**（独立安装副本）
- 目标: 让 Davie 通过解耦工具调用 StackChan 的状态、说话、视觉、伴读和设备控制，并逐项验证；不直接修改脏 Hermes 核心。
- 验证: 新集成单测/MCP或插件发现测试、gateway 38 项回归、零付费 production smoke、tracked secret scan、git diff/status。
- 边界: ¥0；不调用云端模型；不改 Davie executor/proactivity；不提交凭据；不将设备在线或音轨订阅冒充真人声学通过。

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

### 【完成】Codex 2026-07-23 04:22 Asia/Singapore — Davie StackChan status/capability tool
- 发现: StackChan 高层 API 已存在，但 Davie 没有独立工具发现 Gateway 健康、设备会话和能力；直接改 Hermes 核心会与 325 个在途改动耦合。
- 修复: 新增独立 `jm-stackchan` 插件骨架、标准库 Gateway client、只读 `stackchan_status` 工具及脱敏错误合同。
- 验证: `pytest -q integrations/hermes-stackchan/test_plugin.py` -> 4 passed；Gateway `uv run pytest -q` -> 38 passed；`compileall`、`git diff --check` exit 0。
- 花费: ¥0；没有调用任何模型或云端 API。
- 边界: 未改 Hermes 核心，未泄露 token/设备标识，未声称真人声学通过。
- 后续: 实现主动说话与摄像头解释工具，并分别验证在线/离线错误语义。

### 【进行中】Codex 2026-07-23 04:22 Asia/Singapore — Davie StackChan speech and vision tools   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, STACKCHAN_DAVIE_LOOP.md
- 目标: 注册 `stackchan_say` 与 `stackchan_vision`，自动选择唯一在线或默认设备，离线时给出可执行唤醒提示。
- 验证: 插件 HTTP 合同单测、Gateway 38 项回归、compileall、diff check。
- 边界: ¥0；不调用模型；不伪造真实扬声器/摄像头验收。

### 【完成】Codex 2026-07-23 04:24 Asia/Singapore — Davie StackChan speech and vision tools
- 发现: Gateway 的主动说话/摄像头能力只能在设备活跃会话中使用，Davie 需要自动选中默认/唯一设备，并在离线时明确要求用户说 `Davie` 唤醒。
- 修复: 新增 `stackchan_say`、`stackchan_vision`，实现受认证设备选择、输入长度约束、视觉静默模式及脱敏离线错误。
- 验证: 插件测试 7 passed；Gateway 回归 38 passed；compileall/diff check exit 0。
- 花费: ¥0；测试未调用任何模型。
- 边界: 未把模拟 HTTP 结果表述为真实扬声器/摄像头物理通过。
- 后续: 实现可恢复伴读的 load/status/play/pause/resume/stop/clear。

### 【进行中】Codex 2026-07-23 04:24 Asia/Singapore — Davie StackChan resumable reader tool   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, STACKCHAN_DAVIE_LOOP.md
- 目标: 让 Davie 可离线预装文章/书籍并在设备唤醒后逐句播放、暂停和续读。
- 验证: reader HTTP 合同测试、输入边界测试、Gateway 38 项回归、compileall、diff check。
- 边界: ¥0；不解析原始二进制文件，复用 Davie Document Intake 提取后的文本；不声称真人听声通过。

### 【完成】Codex 2026-07-23 04:28 Asia/Singapore — Davie StackChan resumable reader tool
- 发现: 伴读需要支持设备离线时预装内容，且不能把二进制文件解析重复塞进机器人插件；应复用 Document Intake，只直接读取受控目录的 UTF-8 TXT/Markdown/HTML。测试还发现并修复了方法缩进和测试状态共享问题。
- 修复: 新增 `stackchan_reader` 的 load/status/play/pause/resume/stop/clear，HTML 可读正文提取、500k 字符限制、2MB 源文件限制和可配置目录边界。
- 验证: 插件测试 11 passed；Gateway 回归 38 passed；compileall/diff check exit 0。
- 花费: ¥0；没有模型调用。
- 边界: 未重复实现 PDF/DOCX 解析；未声称物理播放听感通过。
- 后续: 实现受控音量、头部和 LED 白名单操作。

### 【进行中】Codex 2026-07-23 04:28 Asia/Singapore — Davie StackChan device controls   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, STACKCHAN_DAVIE_LOOP.md
- 目标: 仅暴露经过固件合同验证的高层设备动作，禁止任意 MCP 名称/参数透传。
- 验证: 映射与边界单测、未知动作拒绝、Gateway 38 项回归、compileall、diff check。
- 边界: ¥0；不调用模型；不声称真实舵机/LED 物理变化通过。

### 【完成】Codex 2026-07-23 04:31 Asia/Singapore — Davie StackChan device controls
- 发现: Gateway 有通用 MCP 透传入口，但直接暴露会允许模型发明工具名和越界参数。
- 修复: 新增 `stackchan_control`，只映射固件确认的 volume/head/LED 三类动作，并在发网前验证所有范围。
- 验证: 插件测试 19 passed（含 3 类映射及 5 类拒绝）；Gateway 回归 38 passed；compileall/diff check exit 0。
- 花费: ¥0。
- 边界: 未暴露任意 MCP 透传，未声称真实舵机/LED 物理动作通过。
- 后续: 补齐本地提醒创建、查看和停止。

### 【进行中】Codex 2026-07-23 04:31 Asia/Singapore — Davie StackChan local reminders   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, STACKCHAN_DAVIE_LOOP.md
- 目标: 通过固件白名单 MCP 合同创建/list/stop 设备本地提醒。
- 验证: reminder 映射/边界单测、Gateway 38 项回归、compileall、diff check。
- 边界: ¥0；不把本地提醒描述成跨重启持久日历任务。

### 【完成】Codex 2026-07-23 04:34 Asia/Singapore — Davie StackChan local reminders
- 发现: 固件已有 create/list/stop reminder MCP，但它是设备通电期间的本地便利提醒，不应伪装成持久 cron。
- 修复: 新增 `stackchan_reminder`，固定三项工具映射、结果内容解析、时长/消息/repeat/id 边界及生命周期回执。
- 验证: 插件测试 25 passed；Gateway 回归 38 passed；compileall/diff check exit 0。
- 花费: ¥0。
- 边界: 未修改 Hermes cron，未将提醒描述为跨重启持久。
- 后续: 可重复安装插件、配置本地凭据引用、验证 Hermes 工具发现。

### 【进行中】Codex 2026-07-23 04:34 Asia/Singapore — install and register jm-stackchan   (TTL 30m)
- 正在改: integrations/hermes-stackchan/**, docs/**, STACKCHAN_DAVIE_LOOP.md, /Users/jm2m/.hermes/plugins/jm-stackchan/**, /Users/jm2m/.hermes/stackchan.json, /Users/jm2m/.hermes/secrets/stackchan-admin-token, /Users/jm2m/.hermes/config.yaml（仅通过 Hermes 官方插件启用命令）
- 目标: 以独立插件安装，不改 325 项脏 Hermes 核心；六个工具在真实 Hermes registry 可发现。
- 验证: 安装脚本单测/干跑、插件 list/status、registry 六工具、Gateway 生产只读 smoke、源/安装 hash 一致。
- 边界: ¥0；secret 只写 0600 文件且不输出；不直接重排 config.yaml。

### 【完成】Codex 2026-07-23 04:41 Asia/Singapore — install and register jm-stackchan
- 发现: Hermes 0.18.2 首次 `plugins enable` 存在时序缺口，只写 `plugins.enabled` 而未把新 toolset 加入平台；配置文件还受 `uchg` 完整性锁保护。
- 修复: 新增可重复安装器与文档；secret 独立 0600；用官方 `hermes tools enable --platform` 补齐 cli/telegram/feishu 等平台后恢复 `uchg`。未修改 Hermes 源码。
- 验证: 安装器+插件 26 passed；Gateway 38 passed；生产 registry 6 tools；cli/telegram/feishu 均解析 `stackchan=true`；源/安装 hash 相同；真实 Gateway health 及临时离线 reader load/status/clear 通过。
- 花费: ¥0；没有模型调用。
- 边界: token 未输出/入库；配置已 NAS 备份；未强行修改 Hermes 不识别的 `teams` 平台。
- 后续: 重启 Davie Gateway，让长驻进程载入插件并执行真实会话 smoke。

### 【进行中】Codex 2026-07-23 04:41 Asia/Singapore — production Davie StackChan activation   (TTL 30m)
- 正在改: 仅运行态 Gateway 重启、验证日志、docs/**, STACKCHAN_DAVIE_LOOP.md
- 目标: 长驻 Davie 加载六个 StackChan 工具，Web/Telegram/Feishu 共用同一注册结果。
- 验证: pre/post PID、health、启动日志无新 traceback、实际 agent tool schema/status smoke、Gateway/插件回归。
- 边界: ¥0；不发送用户消息、不调用云端；不更新 integrity baseline 直到全量检查完成。


### 【完成】Codex 2026-07-23 05:07 Asia/Singapore — production Davie StackChan activation
- 发现: 六个工具已经注册，但最终验收必须证明真实 Davie 会话会调用工具，且不能把设备配置、网络可达或 Track/registry 状态冒充物理唤醒。首次系统 Python 测试失败是错误解释器缺 pytest；改用锁定项目 venv 后通过。one-shot 标准输出曾与会话落盘结果不同，trace 是本次工具生命周期的权威证据。
- 修复: 补齐 CLI/Web API/Telegram/飞书 toolset，重启长驻 Gateway，增加面向用户的聊天控制说明及面向维护者的独立插件部署合同；未修改 325 项在途 Hermes 核心工作树。
- 验证: 插件/安装器 26 passed；Gateway 38 passed；compileall、HTML 结构、diff check 通过；四个平台均显示 stackchan enabled；生产 registry 精确包含六工具；真实 Davie trace 为 tool_call -> stackchan_status -> Gateway 0.2.0 ok；say/vision/control/reminder 离线合同均返回可执行唤醒提示；reader load/status/clear 通过且清理；Hermes :8642 与 Rock5B :8793 健康；Rock5B systemd active；设备 Wi-Fi 3/3 与 USB serial 均可达；重启后日志无新 ERROR/Traceback。
- 花费: ¥0；没有调用云端或付费模型/API。
- 边界: 未发送 Telegram/飞书测试消息，未改 Davie executor/proactivity，未记录真实凭据；真人近距离唤醒、真实扬声器听声、摄像头现场画面、舵机/LED 动作与播放中打断仍标记 pending-human。
- 后续: 用户在设备旁说 `Davie` 建立会话后，按用户指南完成一次六项物理验收；软件实现与生产集成已完成。
