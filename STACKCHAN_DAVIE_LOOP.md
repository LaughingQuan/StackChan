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
  - "Do not format the user's 16 GB TF card; TF-backed features must remain optional and degrade cleanly when the card is absent."
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

## Run Contract · Desktop Robot Interaction P0-P8

```yaml
project: "Davie Desktop Robot interaction stack (/Users/jm2m/Documents/stackchan-davie, /Users/jm2m/Documents/davie-platform, /Users/jm2m/Documents/davie-media-gateway)"
scope: "Implement DAVIE_DESKTOP_ROBOT_INTERACTION_OPTIMIZATION_PLAN_2026-07-24.html strictly from P0 through P8. Each phase must pass its zero-cost and physical exit gates before the next phase starts."
autonomy_level: "bounded"
boundaries:
  - "Money budget is zero; no paid or cloud API calls."
  - "Do not modify Davie executor/proactivity core."
  - "Do not replace the production jm-stackchan plugin or claim production capability before canary and physical evidence."
  - "Do not format the TF card, expose credentials, or use TF as the only copy of user data."
  - "Do not claim wake, audible playback, barge-in, camera understanding, or reader endurance from protocol-only evidence."
  - "Do not enter P1 until P0 identity, connectivity, diagnostics, and restart gates pass; apply the same hard gate between every later phase."
stop:
  - "A phase remains failing after three bounded repair attempts."
  - "A physical action or product decision is required and no dependency-safe work remains."
  - "Two consecutive loops find no valuable in-scope work."
budget:
  money: 0
verify:
  zero_cost:
    - "Gateway and plugin test suites exit 0."
    - "Firmware host tests and full ESP-IDF build exit 0 for firmware changes."
    - "Davie Platform full tests, contract validation, and wheel build exit 0 for platform changes."
    - "Media protocol fixtures and local worker smoke checks exit 0 for media changes."
    - "Secret scan and git diff --check exit 0."
    - "Every physical claim includes device monotonic timestamps and an observable human/device receipt."
paid_allowed_after_zero_cost: false
comms_log: "/Users/jm2m/Documents/stackchan-davie/STACKCHAN_DAVIE_LOOP.md"
progress_log: "/Users/jm2m/Documents/stackchan-davie/STACKCHAN_DAVIE_LOOP.md"
handoff:
  - "Record each phase's implementation, exact test output, physical evidence, residual risks, commit IDs, deployment state, and rollback point."
```

## Claims

### 【已关闭】Codex 2026-07-23 22:38 Asia/Singapore — StackChan Readiness P0 control plane (TTL 6h)
- 正在改: `integrations/davie-gateway/**`, 必要时 `firmware/**`, `docs/**`, `STACKCHAN_DAVIE_LOOP.md`
- 目标: 补齐会话生命周期、超时休眠/显式关闭、no-speech/低质量输入门禁、避免误打断与取消风暴，并形成可观察验收证据。
- 验证: 每个原子阶段新增/更新测试后执行 Gateway 全量回归；固件若改动则追加 host test、完整 ESP-IDF build、分区兼容和 secret scan；部署后做 Rock5B live smoke 与 StackChan 非人工证据检查。
- 边界: ¥0；不调用付费/云端模型；不改 Davie executor/proactivity 核心；不把合成声音或网络可达冒充真人唤醒/听声通过；真人测试缺失时保持明确 pending-human。

### 【已关闭】Codex 2026-07-23 04:16 Asia/Singapore — Davie callable StackChan integration   (TTL 30m)
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

### 【完成】Codex 2026-07-23 22:51 Asia/Singapore — session lifecycle and sleep control
- 发现: 设备进入语音会话后没有 inactivity watchdog、本地结束口令或管理端关闭合同；自定义唤醒词在 Listening 期间关闭，导致长驻会话会直接破坏下一次可靠唤醒。
- 修复: 新增 `connecting/ready/listening/transcribing/thinking/speaking/sleeping/closed` 状态证据、120 秒可配置无活动休眠、本地 `Goodbye Davie/go to sleep/休息吧`、受认证管理端 sleep API、close reason 与活动时间诊断。
- 验证: Gateway `uv run pytest -q` 42 passed；锁定 venv compileall、`git diff --check` 通过。测试覆盖语音休眠不调用模型、watchdog 自动断开、权限及离线错误合同。
- 花费: ¥0；未调用任何模型/API。
- 边界: 未把单元测试表述为真人唤醒通过；生产部署留到后续 P0 软件门禁整体通过后统一进行。

### 【完成】Codex 2026-07-23 23:01 Asia/Singapore — ASR quality gate and staged barge-in
- 发现: 每个 120ms speech start 都会立即取消生成；不足最小语音时长的噪声一旦进入 speaking 状态会卡到 20 秒 max turn；ASR 的 `Jason, Jason...`、纯名字/唤醒尾音和不可能语速的幻觉会直接调用 Davie。全局人名 hotword 还会放大错误偏置。
- 修复: 新增音频回合的时长/有效语音/RMS 证据；短噪声在 silence deadline 主动放弃；打断改为 possible -> 360ms confirmed/完整回合两阶段；只保留设备相关 hotword；新增纯名字/唤醒、纯 filler、异常转写速率门禁与完整诊断计数。
- 验证: Gateway `uv run pytest -q` 47 passed；锁定 venv compileall、`git diff --check` 通过。新增覆盖 Media 元数据合同、短噪声不取消、确认语音才取消、名字重复与长幻觉不进入 Davie。
- 花费: ¥0；没有调用模型，回归使用固定 fixture。
- 边界: 这是服务端防误触与证据层，不宣称已经替代真人声学标定；唤醒词阈值仍需近场/远场人工矩阵确认。

### 【完成】Codex 2026-07-23 23:14 Asia/Singapore — Davie lifecycle tool and 0.3.0 release candidate
- 发现: Gateway 已有 sleep API，但 Davie 的独立 StackChan 插件只能控制音量/头部/LED，无法主动结束自己的桌面语音会话；运行和维护文档也没有说明新门禁证据。
- 修复: `stackchan_control` 新增严格白名单 `sleep`，调用同源受认证生命周期 API；Gateway 升级到 0.3.0，补齐环境变量示例、运行说明、质量门禁与“不把网络在线当物理通过”的验收边界。
- 验证: Gateway 47 passed；Hermes 插件 26 passed；sdist/wheel 构建通过；compileall/diff check 通过；通用 secret 关键字扫描只命中既有配置/测试引用，未发现本轮新增凭据。
- 花费: ¥0。
- 边界: 尚未更新已安装插件和 Rock5B 生产服务；下一阶段先提交原子变更，再执行备份、部署和 live smoke。

### 【完成】Codex 2026-07-23 23:36 Asia/Singapore — production 0.3.0 and post-disconnect evidence
- 发现: 会话一断开就从 `/v1/devices` 消失，导致真人测试后无法诊断到底是空音频、ASR 拒绝、误打断还是正常 sleep。
- 修复: 增加受认证的 bounded recent-session evidence（默认 20 条、无原始音频）；新增可重复 lifecycle live smoke；Rock5B 0.2.0 软件/配置已备份到 NAS，0.3.0 已安装并重启；本机 Hermes 插件副本已原子更新且源/安装 hash 一致。
- 验证: Gateway 48 passed；完整 live voice smoke 通过 `hello/stt/llm/tts` 并返回 138,240 PCM bytes，8.998 秒完成；lifecycle smoke 验证 ready 状态、admin sleep、Sleeping 事件和 transport close 全通过；生产 PID 更新、health 0.3.0、日志无新错误。
- 花费: ¥0；完整语音 smoke 只调用本地 NVIDIA 与本地 Davie。
- 边界: 没有把协议 smoke 当成真人唤醒/人耳播放证据；Hermes 长驻 Gateway 将在最终全量门禁后统一重启加载插件。

### 【完成】Codex 2026-07-24 00:02 Asia/Singapore — direct Davie firmware candidate
- 发现: 已部署固件仍要求完整的 `Hello Davie`，不符合用户要求的单词唤醒；重启后系统 PATH 丢失 CMake/Ninja，但 ESP-IDF Python 环境已有可用工具，重复下载没有必要。
- 修复: Davie 固件 overlay 改为唯一唤醒命令 `DAVIE`，保留显示名与阈值；构建明确复用 ESP-IDF 5.5.4 隔离环境，不依赖全局 PATH。
- 验证: firmware host test 1/1 passed；ESP-IDF 5.5.4 全量 reconfigure/build passed；生成配置确认为 `CONFIG_CUSTOM_WAKE_WORD="DAVIE"`；应用镜像 4,407,248 bytes，分区保留 15%；分区表与已验证物理布局一致；NAS 三套 factory/pre-Davie 恢复清单 SHA-256 全部通过。
- 花费: ¥0。
- 边界: 构建通过只表示固件候选可刷写；真人直呼识别率、噪声环境和误唤醒率仍需设备旁人工验收。


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

### 【已关闭】Codex 2026-07-23 04:22 Asia/Singapore — Davie StackChan speech and vision tools   (TTL 30m)
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

### 【已关闭】Codex 2026-07-23 04:24 Asia/Singapore — Davie StackChan resumable reader tool   (TTL 30m)
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

### 【已关闭】Codex 2026-07-23 04:28 Asia/Singapore — Davie StackChan device controls   (TTL 30m)
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

### 【已关闭】Codex 2026-07-23 04:31 Asia/Singapore — Davie StackChan local reminders   (TTL 30m)
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

### 【已关闭】Codex 2026-07-23 04:34 Asia/Singapore — install and register jm-stackchan   (TTL 30m)
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

### 【已关闭】Codex 2026-07-23 04:41 Asia/Singapore — production Davie StackChan activation   (TTL 30m)
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

### 【完成】Codex 2026-07-24 00:42 Asia/Singapore — truthful live-state reporting
- 发现: Davie 在没有活动物理会话时只检索 Knowledge Atlas，并把历史能力说明误报成 “Connected/Ready”；Gateway 健康、IP 可达和知识记录都不能证明机器人此刻已醒着。
- 修复: `stackchan_status` 成为所有 current-state 问题的强制实时工具；回执显式区分 `gateway_reachable`、`active_session`、`no_active_session` 与 `unknown`。Gateway capability manifest 增加唯一的语音会话启动/结束合同，版本统一为 0.3.1。
- 验证: Gateway 48 passed；Hermes Stack-chan 插件与安装器 28 passed；wheel/sdist 构建通过；生产 Gateway 0.3.1、Hermes 插件和长驻 Gateway 已更新。真实 Davie one-shot 正确回答 “Gateway reachable, no active physical device session”，并给出说 `Davie` 后等待 Listening 的操作。
- 花费: ¥0；仅调用本地模型进行回放，无云端或付费调用。
- 边界: 未把协议状态冒充真人唤醒或听声；未修改 Davie executor/proactivity。
- 后续: 修复唤醒后第一段空转写立即报错的用户体验，并继续调查设备网络抖动。

### 【完成】Codex 2026-07-24 01:08 Asia/Singapore — keep listening after wake-only audio
- 发现: 唤醒尾音或用户尚未开始讲话时，第一段空转写会立即显示 `I did not catch that`；初版修复又错误使用会话累计空转写次数，可能让一次历史空结果影响后续正常回合。
- 修复: Gateway 0.3.2 将累计空转写与连续空转写分开。第一次空转写保持 Listening；非实时模式仅连续两次空转写提示重试；任何非空转写都会重置连续计数。诊断状态新增 `consecutive_empty_transcript_count`。
- 验证: session 定向 20 passed；Gateway 全量 50 passed；Hermes 插件与安装器 28 passed；wheel/sdist 构建通过。生产 lifecycle smoke 通过，完整本地 `hello → STT → Davie → TTS` smoke 返回 227,520 PCM bytes、14.196 秒完成；Rock5B systemd active、health 0.3.2、日志无新异常。
- 花费: ¥0；完整 smoke 仅调用本地 NVIDIA 媒体服务与本地 Davie。
- 边界: 0.3.1 运行目录和 systemd 定义已备份到 NAS；未修改凭据、Davie executor/proactivity，未声称真人声学验收通过。
- 后续: Knowledge Atlas 两份 Stack-chan 能力文档已更新并同步 AnythingLLM；下一轮量化 Wi-Fi 抖动及其对唤醒/首包体验的影响。

### 【完成】Codex 2026-07-24 01:45 Asia/Singapore — low-latency powered desktop Wi-Fi
- 发现: 官方 idle 路径把 LOW_POWER 映射成 `WIFI_PS_MAX_MODEM`，station listen interval 为 10；设备日志与 20 包测试呈现约一秒周期延迟，刷写前为 459.846ms average / 928.146ms max。
- 修复: 新增可关闭的 `CONFIG_STACKCHAN_DAVIE_LOW_LATENCY_WIFI`。Davie 本地运行 profile 默认保持 `PERFORMANCE / WIFI_PS_NONE`，但不改变显示休眠；电池优先部署可关闭该选项恢复官方策略。
- 验证: host test 1/1、ESP-IDF 5.5.4 全量与增量构建、Gateway 50、Hermes 插件与安装器 28 全部通过；应用 4,407,328 bytes，分区余量 15%。刷写哈希验证通过，启动日志确认 1.4.3、性能模式和 `Set ps type: 0`。相同 20 包测试降至 4.217ms average / 11.398ms max，空闲后复测 4.303ms / 11.644ms，均 0% loss。生产 voice smoke 返回 216,000 PCM bytes / 11.116s，lifecycle smoke 全通过。
- 恢复: 刷写前完整 16MB 镜像保存于 `/Users/jm2m/NAS/ClawBackups/Hermes/backups/stackchan/pre-low-latency-wifi-20260724-012447`，SHA-256 manifest 校验通过。
- 花费: ¥0；仅使用本地服务。
- 边界: 网络与协议证据不能替代真人近场/远场唤醒、扬声器听感和播放中插话验收，这些仍是 pending-human。

### 【完成】Codex 2026-07-24 02:08 Asia/Singapore — generation-safe voice latency evidence
- 发现: 完整本地语音 smoke 只能看到 11.116 秒总时间，无法区分自然输入/播放时长与 ASR、Davie、TTS 等可优化等待，容易错误调整端点或牺牲回答质量。
- 修复: Gateway 0.3.3 新增 generation-safe `last_turn_timing`，分别记录输入与有效语音时长、Gateway/服务端 ASR、Davie/视觉、回复就绪、TTS 准备、首音频、发送音频和总耗时；空转写、拒绝、设备动作、完成、取消、替代和错误回合分别标记。旧 generation 不能覆盖新回合证据。
- 验证: session 定向 21 passed；Gateway 全量 51 passed；Hermes 插件与安装器 28 passed；compileall、wheel/sdist、diff check 通过。生产升级到 0.3.3，voice canary 返回 141,120 PCM bytes / 8.963 秒；最近会话显示 ASR 286ms、Davie 2,399ms、TTS 1,228ms、首音频 3,927ms、实时发送音频 2,940ms、端点提交后总计 7,130ms。
- 花费: ¥0；仅使用本地 Fun-ASR、Davie 和 CosyVoice。
- 边界: 没有把协议 canary 当做人耳证据，没有调用付费模型，没有修改 Davie executor/proactivity。
- 后续: 优先调查 Davie token stream 与 CosyVoice chunk stream 的首音频流水线；不要继续压缩 900ms 端点静音来换取表面速度。

### 【完成】Codex 2026-07-24 03:06 Asia/Singapore — pipelined spoken response and bilingual recovery
- 发现: 原链路必须等待 Davie 全文后逐句串行 TTS；三句回复后续非播放空隙约 5.907 秒。英文输入还可能受持久化偏好影响改用中文；Hermes 对一个中文回合可出现正常 SSE 结束但零正文，而非流式同请求有正文。
- 修复: Gateway 0.3.11 接入 Hermes SSE；首个完整句在后文生成期间进入 TTS，当前 PCM 播放时仅预取下一句。增加 generation-safe 首个非空文本 delta、逐句 TTS、首音频和后续空隙指标；按当前回合确定中英文；仅对“无正文且无工具/进度事件”的干净空流降级一次非流式；朗读前去除 URL、Markdown、代码块和句首项目符号。
- 验证: Gateway 60 passed；Hermes 插件与安装器 28 passed；ruff、compileall、wheel/sdist、diff check 通过。生产 0.3.11 英文、中文、lifecycle 三类完整协议 smoke 均通过。英文三句首个文本 delta 2.762 秒、首音频 5.927 秒、首音频后非播放空隙 1.271 秒；中文空流兼容回合首个文本 delta 1.088 秒、首音频 3.616 秒且保持中文。设备 20 包 0% 丢包，平均 5.487ms；Rock5B Gateway、NVIDIA ASR/TTS 和 Hermes 0.18.2 均健康，生产日志无新异常。Knowledge Atlas 中英文能力卡完成 ETag 更新、HTML 校验与 AnythingLLM `synced`；Davie 精确检索能返回空流规则和 release identifier `0.3.11`。
- 花费: ¥0；全部使用本地 Fun-ASR、Qwen/Davie 与 CosyVoice。
- 边界: 未调用付费模型，未修改 Davie executor/proactivity；合成 canary 只能证明协议和音频数据链路，真人唤醒率、人耳音质、房间回声和播放中打断仍需现场验收。
- 后续: 将当前未版本化的 NVIDIA media-gateway 纳入独立仓库后，再隔离评估 CosyVoice vLLM/TensorRT 真 chunk streaming；不要直接改生产 worker。Davie 的通用“current version”确定性健康路由会把 Stack-chan 版本问句误判成 Hermes Gateway 状态，精确知识检索不受影响；该路由应在独立 Davie 变更中修复，不能混入本仓库。

### 【已关闭】Codex 2026-07-24 00:00 Asia/Singapore — TF storage and interaction loop (TTL 8h)
- 正在改: `firmware/main/hal/board/**`, `firmware/main/hal/hal_mcp.cpp`, `firmware/main/CMakeLists.txt`, `firmware/main/Kconfig.projbuild`, `firmware/sdkconfig.defaults.davie.example`, `integrations/davie-gateway/**`, `integrations/hermes-stackchan/**`, `docs/**`, `README.md`, `STACKCHAN_DAVIE_LOOP.md`
- 目标: 安全启用 CoreS3 TF 卡，提供可观察、可降级的存储能力，并用于伴读缓存、离线恢复、有限诊断与更流畅的 Davie 交互；每个阶段验证后再继续。
- 验证: firmware host test、完整 ESP-IDF build、Gateway/插件全量测试、secret scan、分区兼容、TF 实卡 mount/read/write/screen coexistence canary、生产服务与设备回归。
- 边界: ¥0；不调用付费/云端模型；不修改 Davie executor/proactivity；不格式化 TF 卡；不把协议或设备在线冒充真人声学通过；保留官方恢复镜像与 NVS。

### 【完成】Codex 2026-07-24 04:05 Asia/Singapore — P1 optional TF edge-storage foundation
- 发现: CoreS3 的 TF 与 LCD 共享 SPI3，GPIO35 同时承担 LCD D/C 输出和 TF MISO 输入；原固件既未供电也未挂载 TF。首次真机日志还暴露了 compact log 不正确渲染 64 位容量参数的问题。
- 修复: 按 Espressif CoreS3 BSP 的供电与共享总线合同启用 TF，挂载 `/tf` 且明确禁用自动格式化；创建 Davie 的 library/cache/diag 目录；启动时执行 tiny write/flush/fsync/read/compare/delete 自检；提供只读状态与人工触发自检 MCP；无卡或损坏时仅降级存储。修正容量日志为 ESP 可稳定输出的 MiB 数值。
- 验证: 固件 host binary exit 0；Gateway `60 passed`；完整 ESP-IDF 5.5.4 build exit 0，app `0x4407d0`、14% free；旧/新 3 KiB 分区表 `cmp` exit 0；NAS 16 MiB full flash、NVS、分区表和候选镜像全部 SHA-256 `OK`；真机两次启动均显示 `TF card ready`，最终容量 `14895 MiB`、writable=1，随后 LCD、camera、touch、audio、Wi-Fi、wake model 全部正常且无 panic/reboot；设备 ping 3/3、Gateway 0.3.11 health OK。
- 花费: ¥0；没有调用付费或云端模型/API。
- 边界: 未格式化 TF、未存储凭据或原始麦克风音频、未修改 Davie executor/proactivity；启动日志与网络可达不冒充真人唤醒或人耳播放证据。
- 后续: 在 TF 抽象上增加小型本地笔记、伴读断点与有界诊断日志，并通过 Gateway/Davie 工具暴露；所有操作保持非首音频关键路径。

### 【完成】Codex 2026-07-24 04:29 Asia/Singapore — P2 bounded TF edge memory
- 发现: TF 卡适合保存短笔记、伴读断点和有限诊断，不适合作为原始音频或整本资料的第二主存储。首次真机启动还发现 FAT 8.3 文件名会拒绝 `events.log.tmp`，这是模拟测试无法发现的真实介质兼容问题。
- 修复: 增加最多 32 条短笔记、单一伴读断点、最多 48 条诊断事件及滚动容量上限；所有写入使用 flush/fsync/rename，失败仅降级 TF 功能。Gateway 增加无需 LLM 的确定性“保存/读取笔记、检查 TF”路由和异步合并断点镜像；Hermes 独立插件增加严格白名单 `stackchan_storage`。原子临时文件改为 FAT 兼容的 `notes.tmp`、`reader.tmp`、`events.tmp`。
- 验证: Gateway `62 passed`；Hermes 插件 `34 passed`；两套 Ruff 门禁和 `git diff --check` 通过；firmware host test 1/1；ESP-IDF 完整构建通过，app `0x444120`、14% free；分区表与刷写前 3 KiB 备份 `cmp` exit 0；app-flash 哈希校验通过。真机启动诊断从首次的临时文件写失败修复为无告警，`14895 MiB`、writable=1，8 个 storage MCP 工具全部注册，LCD/camera/touch/audio/Wi-Fi/wake model 正常。合成 Mac 唤醒未建立会话，因此没有把它冒充 MCP 或真人声学通过；MCP 请求/响应及边界由 Gateway/插件测试覆盖。
- 花费: ¥0；没有调用付费或云端模型/API。
- 边界: 未格式化 TF；未写凭据、原始音频或长文档；未修改 Davie executor/proactivity；启动与合成 canary 不替代真人唤醒/听声。
- 后续: 增加明确的屏幕交互提示与物理触控兜底说明，减少“唤醒失败时不知道下一步”的挫败；部署 Gateway/插件后用真人会话补做真实 MCP 读写。

### 【完成】Codex 2026-07-24 04:50 Asia/Singapore — P3 discoverable voice/touch interaction
- 发现: 官方 UI 已经支持点按头像切换语音会话，但空闲屏幕、Gateway 能力合同和 Davie 工具均没有告诉用户；唤醒漏检后只剩反复说唤醒词，形成“机器人不能用”的错误体验。继续降低 0.08 唤醒阈值会增加噪声误触发，不是可靠修复。
- 修复: 空闲屏幕固定显示 `Say "Davie" or tap me`，进入收听后显示 `Listening...`；保留本地 `Davie` 语音优先，并把点脸一次开始/结束会话作为正式无模型兜底。Gateway capability manifest、Hermes live status 和中英文帮助回复均暴露同一操作合同。
- 验证: Gateway `62 passed`；Hermes 插件 `34 passed`；两套 Ruff 基线门禁通过；firmware host test `1/1`；ESP-IDF 完整构建无新增警告，app `0x444170`、14% free；分区表与 NAS 刷机前备份逐字节一致；仅刷应用分区且哈希验证通过。真实启动日志确认 TF `14895 MiB` 可写、8 个存储 MCP、LCD、触摸、摄像头、双工音频、Wi-Fi、低延迟模式和 `Davie` 唤醒模型全部正常，并确认空闲提示代码已经执行。
- 花费: ¥0；没有调用付费或云端模型/API。
- 边界: 日志和代码不能替代真人看到屏幕、实际点按、近场唤醒及人耳听声；这些仍需用户在设备旁最终确认。没有修改 Davie executor/proactivity，也没有降低唤醒阈值。
- 后续: 发布 Gateway/插件合同，更新人类可读 Knowledge Atlas 使用指南，并执行生产服务、协议、媒体和设备深度回归。

### 【完成】Codex 2026-07-24 05:55 Asia/Singapore — P4 production interaction and truthful live state
- 发现: 设备能力说明、Gateway 状态和物理设备会话过去容易被模型混在一起；知识库历史不能证明机器人现在在线。Web/CLI 即使收到“逐字返回”提示，本地模型仍可能把“黑屏可能是息屏”改写成概率判断。状态路径如果仍读取完整 capability manifest，也会浪费一次无关 HTTP 请求。
- 修复: Telegram/飞书的明确实时状态问题由 `pre_gateway_dispatch` 在调用模型前直接回答；Web/CLI 使用带 30 秒 TTL、最多 64 会话、读取后即删除的认证答案缓存，在 `transform_llm_output` 阶段逐字替换模型改写。状态 fast path 不再下载 capability manifest；完整能力查询仍按需保留。插件 manifest 补齐 `stackchan_storage` 与三个运行时 hook。
- 验证: Hermes 插件 `44 passed`；真实 CLI 回合返回认证原文，不再出现“极大概率”或 Docker/Rock5B-body 幻觉；Knowledge 与 Solution SSE 重启后均为 `connected`。插件源码和安装副本逐文件一致，Gateway PID 受控切换且 Hermes 0.18.2 health OK。
- 花费: ¥0；没有调用付费或云端模型/API。
- 边界: Telegram/飞书可完全跳过模型；CLI/Web 的核心 Agent 仍会运行一次后再被认证答案替换，因此答案准确但 CLI 实测仍约 7 秒。若 Hermes 未来开放通用 API/Web pre-dispatch direct-response，可再去掉这次模型调用，不应修改 Davie executor 来实现。

### 【完成】Codex 2026-07-24 06:42 Asia/Singapore — P5 UTF-safe storage and deep regression
- 发现: TF 短笔记原先按原始字节截断，极端情况下可能切开中文或 Emoji；备份清单还错误地把 `SHA256SUMS` 自身纳入哈希，产生一个假失败。最终回归时机器人本体网络 5/5 不可达且没有 USB 串口，不能继续刷写或伪造真人验收。
- 修复: 抽出无 ESP 依赖的 UTF-8 单行规范化与 JSON escape 模块，非法序列安全跳过，截断只发生在完整 code point 边界；新增中英文、Emoji、非法 UTF-8、空白和 JSON 单测。重建备份清单时排除自身。完成 TF 创意使用指南、操作边界和最终 HTML 报告。
- 验证: Gateway `62 passed`、Hermes 插件 `44 passed`、固件 host `2/2 passed`；两套 compileall 与 fatal Ruff 门禁、`git diff --check`、wheel/sdist 全部通过。ESP-IDF 5.5.4 完整 reconfigure/build 通过，app `0x444400`、14% free；最终固件 SHA-256 `ff8644cb771183d11d86f4b76a3b1d6f1741d0a0be17ac646269e11788eccf86`；分区表与物理 3 KiB 备份逐字节一致，NAS full flash/NVS/分区/候选镜像全部校验通过。生产 lifecycle smoke 与本地 `hello → STT → LLM → TTS` 通过，后者返回 285,120 bytes PCM。
- 花费: ¥0；全部使用本地服务。
- 边界: 此前真机已证明 TF 14,895 MiB 可写、8 个 storage MCP 与屏幕/触控/摄像头/音频/Wi-Fi/唤醒同时工作；本轮最终 UTF-8 加固因设备不在线尚未刷入。真人唤醒、点脸、人耳音质、房间噪声和真实打断仍是 pending-human。

### 【完成】Codex 2026-07-24 06:50 Asia/Singapore — TF storage and interaction loop closed
- 完成: P1 可选 TF 基础、P2 有界边缘记忆、P3 语音/触控双入口、P4 可信实时状态与性能 fast path、P5 UTF-8 加固与深度回归全部完成；源代码、安装插件、生产 Gateway、HTML 指南和 Knowledge Atlas 同步进入收尾。
- 发布状态: Stack-chan Gateway 0.4.3、Hermes 插件 0.2.0；最终固件和恢复备份均已生成并校验。机器人重新在线后仅需刷最终 app 镜像并执行文档中的真人验收，不需要重新设计或重做 TF 功能。
- 命门: 没有修改 Davie executor/proactivity；没有格式化 TF；没有保存 Wi-Fi 密码、token、原始音频或整本书；没有把协议 smoke 冒充真人体验。

### 【完成】Codex 2026-07-24 11:39 Asia/Singapore — reconcile stale Stack-chan claims
- 发现: 日志中有 9 个 2026-07-23/24 的 `【进行中】` 标题已经过 TTL，但对应实现、验证、发布和完成记录均存在；代码工作树在本轮开始前为 clean。
- 修复: 将 9 个陈旧标题标记为 `【已关闭】`，保留原始认领和完成证据；新增 Desktop Robot P0-P8 独立运行合同，避免把旧 TF/工具 P 编号与本轮实体交互 P0-P8 混淆。
- 验证: `git status --short --branch` 在协调修复前仅显示 clean branch；`rg -n '【进行中】' STACKCHAN_DAVIE_LOOP.md` 将在新认领写入后只保留本轮有效认领。
- 花费: ¥0；没有调用模型、云端或付费 API。
- 边界: 没有修改运行代码、生产服务、凭据、固件或设备状态。

### 【已关闭】Codex 2026-07-24 11:39 Asia/Singapore — Desktop Robot P0 identity and evidence loop (TTL 8h)
- 正在改: `firmware/main/hal/{hal_mcp.cpp,hal_ws_avatar.cpp}`, `firmware/main/hal/board/{davie_device_attestation.*,stackchan_display.cc}`, `firmware/main/CMakeLists.txt`, `integrations/davie-gateway/**`, corresponding Gateway/firmware tests, P0 report, and this ledger.
- 目标: prove exact firmware/audio/wake/TF/network identity, separate service/device/audio health, preserve one bounded diagnostic timeline, and establish restart/reconnect evidence before any P1 acoustic tuning.
- 验证: focused protocol/session/app tests after each slice; full Gateway suite, firmware host tests/full ESP-IDF build, secret scan, diff check, device hello/MCP receipt, 20 reconnect cycles, and 30-minute online evidence.
- 边界: ¥0; no cloud/model calls; no Hermes executor/proactivity changes; no TF format; no production deployment before zero-cost checks; no P1 changes or physical-success claim before P0 exit.

### 【完成】Codex 2026-07-24 13:18 Asia/Singapore — Desktop Robot P0 software gate
- 固件身份证明: 新增 `self.davie.get_attestation`，回执包含 1.4.3 固件版本、12 位 Git revision、构建时间、ELF SHA256、boot reason、heap、AFE/AEC/codec channels、wake model、TF 状态、Wi-Fi connected/RSSI；不含 SSID、凭据、音频或用户内容。
- 可信状态: Gateway 0.6.0 明确区分 `service_healthy`、`device_connected`、`last_seen_at`、`audio_flowing`、handshake、attestation 与 expected firmware match，并把有界事件时间线原子持久化。
- 受控诊断: 只有管理员显式 arm 才保存 Gateway 实际收到的 AFE output，单次 1-10 秒，实时线程失败隔离，异步写 WAV/manifest，最近本地副本有上限，NAS 保留归档；TF 只记录同一 capture 的起止时间线，不在 ESP32 实时音频线程同步写大文件。
- 恢复反馈: 固件已有 Wi-Fi 自动扫描/重连和 Gateway 5 秒 WebSocket 重连；本轮补齐空实现的屏幕 notification，并为 disconnect/stall/restored 增加去重提示，heartbeat stall 会主动关闭旧 socket 后重连。
- 版本治理: 原未版本化的 media gateway 已建立独立私有仓库 `LaughingQuan/davie-media-gateway`，初始提交 `a327648`，本地测试 `2 passed`。
- 自动验证: Gateway 全量 `80 passed`；Gateway wheel/sdist 0.6.0 构建成功；固件 full ESP-IDF build 成功，app `0x4456f0`、分区剩余 `0xaa910`（13%）；`motion_math_test` 与 `davie_tf_text_test` 均 exit 0；`git diff --check` 通过；新增 diff 未发现真实凭据。
- 仍未通过: 实体设备 `192.168.50.210` 当前离线且无 USB serial，因此未刷最终固件，未取得设备 attestation，未执行物理 20/20 断电重连或连续 30 分钟在线。P0 不得标记整体通过，不进入 P1。
- 花费/边界: ¥0；没有调用云端或付费模型；没有修改 Davie executor/proactivity；没有格式化 TF；没有把模拟 20 次 WebSocket 重连测试冒充物理断电重连。

### 【完成】Codex 2026-07-24 16:50 Asia/Singapore — Desktop Robot P0 engineering and endurance gate
- 实体恢复: 设备通过 USB 与 `192.168.50.210` 恢复在线；刷写后的 MCP attestation 精确匹配 `stack-chan 1.4.3`、源码 `032f1a60f0ec` 与 ELF SHA256 `695fc028…bb682f7`。TF 14,895 MiB 可写、自检通过，AFE、设备 AEC、参考声道与低延迟 Wi-Fi 均由实体设备回执。
- 现场修复: 修复 attestation 中 64 位 TF 容量格式化触发的 newlib nano 崩溃；修复 NAS 支持内容写入但拒绝 Unix metadata 时 `copystat` 导致诊断归档失败。Gateway 升级到 0.6.1；源码提交 `8761d5ea4eea72a40ac4a65b4931269fbd1e74c0`，部署固件保持可证明的 `032f1a60f0ec`。
- 重连/耐久: 20/20 次自动 USB 硬复位均完成 USB 重新枚举、Wi-Fi 恢复和 ping 3/3，平均 7.670 秒、最慢 7.754 秒。30 分钟监测 60/60 样本通过、零失败，持续 1770.037 秒，平均 ping 4.587ms、最大 12.462ms。
- 最终复核: 耐久后第 6 次 Mac 合成 `Hey, Davie` 建立完整会话；handshake、identity、firmware expectation、attestation 与 audio flowing 全部通过，设备 uptime 2,039,403ms，随后管理员休眠正常关闭会话。
- 音频诊断: 一次显式授权的 2,000ms/64,044-byte/16kHz WAV 已定位到 Gateway 实际 AFE output；本地与 NAS SHA256 均为 `27634f38…40acd0`，归档状态 `synced`。
- 自动验证: Gateway 81 passed；固件 host 2/2；ESP-IDF `fullclean` 后单进程完整 build 成功，app `0x4459c0`、13% free；Davie Platform 196 passed，structure/contracts/AsyncAPI/Ruff/compile/wheel/restart smoke 全部通过。生产 Stack gateway active、`NRestarts=0`、无新 traceback/exception。
- 证据: `/mnt/nas-backups/Hermes/diagnostics/stackchan-p0/20260724` 保存重连、耐久、最终 attestation 与受保护诊断，4 个 JSON 的 SHA256 清单逐一通过。
- 边界: ¥0；没有调用模型、云端或付费 API；没有修改或重启 Davie Gateway/executor/proactivity；没有格式化 TF。自动硬复位不冒充 20 次真人拔电，合成音频第 6 次命中不冒充真人唤醒率；P1 必须修复 raw-channel wake path 并通过真人声学门。

### 【完成】Codex 2026-07-24 17:47 Asia/Singapore — Desktop Robot P1 wake front end and pre-roll implementation
- 正在改: `firmware/xiaozhi-esp32/main/audio/**`, related firmware host tests/configuration, P1 evidence report, and this ledger.
- 目标: feed the custom `Davie` wake detector with the best available AFE-processed microphone signal, preserve bounded pre-roll so speech immediately after wake does not lose its first word, and keep touch-to-talk as a deterministic fallback.
- 验证: reproduce the current raw-channel behavior; focused host tests after each slice; clean single-process ESP-IDF build; exact app-flash/attestation; bounded synthetic wake matrix and first-word audio evidence; full Gateway/firmware regression before any human acoustic gate.
- 边界: ¥0; no cloud/model calls; no Davie Gateway/executor/proactivity changes; no TF format; no blind threshold reduction; no synthetic evidence reported as human wake, audible playback, or room-noise acceptance.
- 发现: custom MultiNet previously consumed a raw left microphone channel and voice startup discarded a fixed 120 ms, so AEC/NS were bypassed and the first post-wake word could be clipped.
- 修复: custom wake now consumes `AFE_TYPE_SR` processed mono with configured AEC/NS/VAD; a channel-aligned 500 ms bounded bridge carries wake-to-conversation PCM; stale audio expires at 5 seconds; fixed warmup discard is removed; malformed interleaved PCM fails closed.
- 验证证据: `cmake --build firmware/build-host-tests-p1 --parallel 1 && ctest --test-dir firmware/build-host-tests-p1 --output-on-failure` -> 3/3 passed; `idf.py -B build-davie-p1 build` -> success, app `0x446b60`, 13% free; generated upstream patch applied cleanly to a fresh `v2.2.4` clone and reproduced the vendored tree except ignored generated `lang_config.h`.
- 花费: ¥0。
- 后续: commit this verified implementation, rebuild from the committed revision, back up the current device image to NAS, flash app-only, then collect boot/heap/attestation/wake evidence before requesting human acoustic validation.

### 【进行中】Codex 2026-07-24 17:48 Asia/Singapore — Desktop Robot P1 physical deployment and automated acceptance (TTL 8h)
- 正在改: P1 deployment evidence/report, device app partition, and this ledger.
- 目标: prove the committed P1 firmware boots reliably, reports truthful AFE/pre-roll attestation, retains Wi-Fi/TF/Gateway functionality, and improves bounded synthetic wake/first-word behavior without panic, WDT, or stale replay.
- 验证: committed-revision clean build; verified NAS backup; app-only flash/readback; serial boot and heap audit; MCP attestation; repeated synthetic wake and first-word canaries; Gateway/firmware regression.
- 边界: ¥0; no cloud/model calls; no Davie Gateway/executor/proactivity changes; no NVS/TF/assets write; no automated evidence represented as human acoustic acceptance.
