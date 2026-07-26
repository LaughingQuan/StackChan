from pathlib import Path


def main() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "main" / "hal" / "hal.cpp"
    ).read_text(encoding="utf-8")
    heartbeat = source.index("davie::device::StartHeartbeat();")
    event_loop = source.index("hal_bridge::start_xiaozhi_app();")
    if heartbeat >= event_loop:
        raise SystemExit(
            "heartbeat must start before the non-returning official event loop"
        )
    print("firmware lifecycle contract: PASS")


if __name__ == "__main__":
    main()
