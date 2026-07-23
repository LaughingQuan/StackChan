# StackChan Open-Source

## Davie local runtime fork

This fork keeps the official StackChan 1.4.3 firmware as the hardware and UI
baseline, then adds a small, removable integration for a local Davie runtime.
The device still uses the upstream launcher, AI Agent, Xiaozhi WebSocket/Opus
protocol, MCP camera and robot tools, Wi-Fi provisioning, OTA, motion, display,
and audio stack.

The local integration is split by responsibility:

- `firmware/` contains the upstream device firmware plus build-time switches
  for the `Davie` wake command, device AEC, the `DAVIE` launcher label, and an
  assets-size-compatible official English speech model.
- `integrations/davie-gateway/` is a portable Linux service that translates
  the official Xiaozhi protocol to local ASR, Davie, TTS, vision, hardware
  actions, and persistent read-aloud services.
- `docs/DAVIE_LOCAL_RUNTIME_ARCHITECTURE.html` records the upgrade-safe design.
- `docs/STACKCHAN_DAVIE_IMPLEMENTATION_2026-07-23.html` records the verified
  implementation and the remaining physical acceptance boundary.
- `docs/STACKCHAN_DAVIE_USER_GUIDE_2026-07-23.html` is the human-facing voice
  command, reader, camera, menu, and operating-boundary guide.

Wi-Fi credentials and runtime tokens are intentionally absent from Git. Copy
`firmware/sdkconfig.defaults.davie.example` to
`firmware/sdkconfig.defaults.local`, set only local endpoints there, and use
the official device provisioning flow for Wi-Fi.

The TF card is optional. Voice, camera, motion, display, OTA, and Davie still
work without removable storage. When a compatible card is present, the device
mounts it at `/tf` without auto-formatting and exposes bounded local notes,
one reader checkpoint, and a rolling diagnostic log. It never stores
credentials or continuous microphone audio. Gateway reader state remains the
authoritative long-form reading record; the TF checkpoint is a device-side
recovery copy. Notes are normalized and truncated only at complete UTF-8
boundaries, so Chinese text and emoji cannot be persisted as broken byte
sequences.

The Davie build is voice-first. When no explicit device preference exists it
boots directly into the official AI Agent. Say `Davie` once while the device is
idle; after the screen shows `Listening...`, speak requests directly without
repeating the wake phrase. If speech is missed, tap Davie's face once to start
the same local voice session without waiting for ASR. Empty realtime ASR
results are ignored so a wake chime tail or a short noise burst does not replace
`Listening...` with a false failure message. The official launcher and Settings
remain available; the Settings switch is still the authoritative user override.

Current-state questions are handled differently from capability questions.
Telegram and Feishu receive an authenticated local answer before any model is
called. Web/CLI turns use the same evidence and replace model paraphrases with
the exact bounded answer once per session. This prevents a reachable Gateway
or a dark display from being misreported as proof that the physical robot is
online or offline.

<img src="https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/K151_stack_chan_main_pictures_01.webp" width="60%">

Here are StackChan related open-source resources, including source code of the StackChan firmware, remote controller firmware, mobile app (iOS and Android), and server. 

Update of this repo could be a little late than the released firmware and mobile app. 

----

<img src="https://cdn.shopify.com/s/files/1/0056/7689/2250/files/5a589623895f65487717894d9240f6b8.png" width="60%">

**StackChan is a super kawaii AI desktop robot co-created by M5Stack and the user community.** It uses the M5Stack **flagship IoT development kit [CoreS3](https://docs.m5stack.com/en/core/CoreS3)** as its main controller, powered by an ESP32-S3 SoC featuring a 240 MHz dual-core processor, with 16MB Flash and 8MB PSRAM onboard, and supporting Wi-Fi and BLE. The main unit also integrates a 2.0-inch capacitive touch display with a high-strength glass cover, a 0.3 MP camera, a proximity & ambient light sensor, a 9-axis IMU (accelerometer + gyroscope + magnetometer), a microSD card slot, a 1W speaker, dual microphones, and power/reset buttons. 

The **robot body**, connected to the main unit, includes a USB-C interface for power and data, a 550 mAh battery, two feedback servos (360-degree continuous rotation on the horizontal axis and 90-degree movement on the vertical axis), two rows totaling 12 RGB LEDs, infrared transmitter and receiver, a three-zone touch panel, and a full-featured NFC module. 

The **factory firmware** is feature-rich, including an AI Agent, lively and expressive animations, ESP-NOW wireless remote control, and online app downloads. It can connect to a mobile app for video viewing, remote avatar control, and more, and also supports online updates (OTA). The product also supports programming via Arduino, UiFlow2, and other methods, and can connect to various expansion units in the M5Stack ecosystem, making it easy to implement a wide range of custom functions. 

> ⚠️ Do not forcibly rotate any movable parts connected to the motors by hand when you are unsure whether the motors are powered and under control, as this may cause hardware damage. 

- Purchase link: [M5Stack Official Store](https://shop.m5stack.com/products/stackchan-kawaii-co-created-open-source-ai-desktop-robot) | [淘宝 Taobao](https://item.taobao.com/item.htm?id=1042238294510)

- Product document page: [English](https://docs.m5stack.com/en/StackChan) | [日本語](https://docs.m5stack.com/ja/StackChan) | [中文](https://docs.m5stack.com/zh_CN/StackChan)

- Board support package: https://github.com/m5stack/StackChan-BSP

Thank you to the contributors of the StackChan community, especially: 

| ![](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/avatar_stack_chan.jpg) | ![](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/avatar_takao.jpg) |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [@stack_chan](https://x.com/stack_chan)                                          | [@mongonta555](https://x.com/mongonta555)                                   |
| Shinya Ishikawa                                                                  | Takao Akaki                                                                 |
