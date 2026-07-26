from pathlib import Path


def main() -> None:
    firmware_root = Path(__file__).resolve().parents[1]
    hal_source = (firmware_root / "main" / "hal" / "hal.cpp").read_text(
        encoding="utf-8"
    )
    heartbeat = hal_source.index("davie::device::StartHeartbeat();")
    event_loop = hal_source.index("hal_bridge::start_xiaozhi_app();")
    if heartbeat >= event_loop:
        raise SystemExit(
            "heartbeat must start before the non-returning official event loop"
        )

    heartbeat_source = (
        firmware_root / "main" / "hal" / "davie_device_heartbeat.cc"
    ).read_text(encoding="utf-8")
    loop_start = heartbeat_source.index("void heartbeat_loop(void*)")
    if "std::unique_ptr<Http> http;" not in heartbeat_source[loop_start:]:
        raise SystemExit(
            "heartbeat HTTP client must outlive each request to avoid disconnect races"
        )
    post_start = heartbeat_source.index("bool post_heartbeat(")
    post_body = heartbeat_source[post_start:loop_start]
    if "http->Close()" in post_body:
        raise SystemExit(
            "heartbeat must not close while async disconnect callbacks are active"
        )
    print("firmware lifecycle contract: PASS")


if __name__ == "__main__":
    main()
