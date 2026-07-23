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

### 【进行中】Codex 2026-07-23 22:38 Asia/Singapore — StackChan Readiness P0 control plane (TTL 6h)
- 正在改: `integrations/davie-gateway/**`, 必要时 `firmware/**`, `docs/**`, `STACKCHAN_DAVIE_LOOP.md`
- 目标: 补齐会话生命周期、超时休眠/显式关闭、no-speech/低质量输入门禁、避免误打断与取消风暴，并形成可观察验收证据。
- 验证: 每个原子阶段新增/更新测试后执行 Gateway 全量回归；固件若改动则追加 host test、完整 ESP-IDF build、分区兼容和 secret scan；部署后做 Rock5B live smoke 与 StackChan 非人工证据检查。
- 边界: ¥0；不调用付费/云端模型；不改 Davie executor/proactivity 核心；不把合成声音或网络可达冒充真人唤醒/听声通过；真人测试缺失时保持明确 pending-human。

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
