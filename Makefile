# Stack-chan Davie —— 三套测试的统一入口。
#
# 存在的理由：这个仓库此前完全没有 CI，81 个 Python 网关测试、5 个 ESP32 固件
# C++ 测试和服务端 Go 测试从不自动执行，而 stackchan-davie-gateway 正以
# 常驻服务跑在 Rock5B 上（被测代码 5648 行，session.py 单文件 2131 行）。
# 本地栈的正确性完全依赖人记得手动跑——这与 Stack-chan 自动 OTA 到官方 1.4.4
# 后离开本地栈两天、服务端一直「健康」却无人告警，是同一个形状。
#
#   make test         跑全部（部署到 Rock5B 前应当先跑这个）
#   make test-gateway 只跑 Python 网关
#   make test-server  只跑 Go 服务端
#   make test-firmware 只跑固件 C++

GATEWAY_DIR := integrations/davie-gateway

.PHONY: test test-gateway test-server test-firmware

test: test-gateway test-server test-firmware
	@echo "跑完了。注意：上面任何一条写「未装」的都代表**没有验证过**，不要当成通过。"

test-gateway:
	@echo "=== 网关（Python）==="
	@cd $(GATEWAY_DIR) && \
		if [ -x .venv/bin/pytest ]; then .venv/bin/pytest -q; \
		elif command -v uv >/dev/null 2>&1; then uv run pytest -q; \
		else echo "找不到 .venv/bin/pytest 也没有 uv，跳过" >&2; exit 1; fi

test-server:
	@echo "=== 服务端（Go）==="
	@if [ ! -d server ]; then echo "  无 server/ 目录"; \
	elif ! command -v go >/dev/null 2>&1; then \
		echo "  ⚠ server/ 存在但本机未装 go —— 这些测试没跑，不是没有" >&2; \
	else cd server && go test ./...; fi

test-firmware:
	@echo "=== 固件（C++）==="
	@if [ ! -d firmware/tests ]; then echo "  无 firmware/tests 目录"; \
	elif ! command -v cmake >/dev/null 2>&1; then \
		echo "  ⚠ firmware/tests 存在（5 个用例）但本机未装 cmake —— 没跑，不是没有" >&2; \
	else \
		cmake -S firmware/tests -B build/firmware-tests >/dev/null && \
		cmake --build build/firmware-tests >/dev/null && \
		ctest --test-dir build/firmware-tests --output-on-failure; fi
