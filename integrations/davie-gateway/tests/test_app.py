from __future__ import annotations

from fastapi.testclient import TestClient

from stackchan_davie_gateway.app import create_app
from stackchan_davie_gateway.clients import DavieReply
from stackchan_davie_gateway.config import Settings
from stackchan_davie_gateway.reader import ReaderLibrary


class NullClient:
    async def close(self) -> None:
        return None


class VisionDavie(NullClient):
    def __init__(self):
        self.received: list[tuple[str, bytes, str, str, str | None]] = []

    async def analyze_image(
        self,
        question: str,
        image_bytes: bytes,
        *,
        mime_type: str,
        device_id: str,
        session_id: str | None = None,
    ) -> DavieReply:
        self.received.append((question, image_bytes, mime_type, device_id, session_id))
        return DavieReply("I can see a blue cup.", session_id or "vision-session-1")


def test_ota_bootstrap_points_to_local_gateway_without_firmware_update() -> None:
    app = create_app(
        Settings(
            public_host="stackchan-gateway.test",
            port=8793,
            device_token="test-token",
            davie_api_key="davie-token",
            admin_token="admin-token",
        ),
        media_client=NullClient(),
        davie_client=NullClient(),
    )
    with TestClient(app) as client:
        response = client.post("/xiaozhi/ota/", json={"device": "test"})
        assert response.status_code == 200
        payload = response.json()
        assert (
            payload["websocket"]["url"]
            == "ws://stackchan-gateway.test:8793/xiaozhi/v1/"
        )
        assert payload["websocket"]["version"] == 1
        assert payload["websocket"]["token"] == "test-token"
        assert "firmware" not in payload


def test_health_never_returns_secret_values() -> None:
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
        ),
        media_client=NullClient(),
        davie_client=NullClient(),
    )
    with TestClient(app) as client:
        payload = client.get("/health").json()
        serialized = str(payload)
        assert "device-secret" not in serialized
        assert "davie-secret" not in serialized
        assert "admin-secret" not in serialized
        assert payload["device_auth_configured"] is True
        assert payload["davie_auth_configured"] is True
        assert payload["admin_auth_configured"] is True


def test_admin_routes_require_the_separate_admin_token() -> None:
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
        ),
        media_client=NullClient(),
        davie_client=NullClient(),
    )
    with TestClient(app) as client:
        assert client.get("/v1/devices").status_code == 401
        assert (
            client.get(
                "/v1/devices",
                headers={"Authorization": "Bearer device-secret"},
            ).status_code
            == 401
        )
        response = client.get(
            "/v1/devices",
            headers={"Authorization": "Bearer admin-secret"},
        )
        assert response.status_code == 200
        assert response.json() == {"devices": []}


def test_runtime_validation_fails_closed_without_credentials() -> None:
    app = create_app(
        Settings(),
        media_client=NullClient(),
        davie_client=NullClient(),
    )
    try:
        with TestClient(app):
            raise AssertionError("lifespan should not start without credentials")
    except RuntimeError as exc:
        assert "missing required StackChan credentials" in str(exc)


def test_camera_explain_uses_local_davie_multimodal_bridge(tmp_path) -> None:
    davie = VisionDavie()
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
            camera_snapshot_dir=str(tmp_path),
        ),
        media_client=NullClient(),
        davie_client=davie,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/vision/explain",
            headers={
                "Authorization": "Bearer device-secret",
                "Device-Id": "stackchan-1",
            },
            data={"question": "What do you see?"},
            files={"file": ("camera.jpg", b"\xff\xd8test\xff\xd9", "image/jpeg")},
        )
        assert client.get("/v1/devices/stackchan-1/camera/latest").status_code == 401
        latest = client.get(
            "/v1/devices/stackchan-1/camera/latest",
            headers={"Authorization": "Bearer admin-secret"},
        )
    assert response.status_code == 200
    assert response.json() == {"success": True, "result": "I can see a blue cup."}
    assert davie.received == [
        (
            "What do you see?",
            b"\xff\xd8test\xff\xd9",
            "image/jpeg",
            "stackchan-1",
            None,
        )
    ]
    assert latest.status_code == 200
    assert latest.content == b"\xff\xd8test\xff\xd9"
    assert latest.headers["content-type"] == "image/jpeg"
    assert latest.headers["cache-control"] == "no-store"


def test_camera_explain_continues_the_active_spoken_session(tmp_path) -> None:
    davie = VisionDavie()
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
            camera_snapshot_dir=str(tmp_path),
        ),
        media_client=NullClient(),
        davie_client=davie,
    )
    headers = {
        "Authorization": "Bearer device-secret",
        "Device-Id": "stackchan-1",
        "Client-Id": "client-1",
    }
    upload = {
        "data": {"question": "What do you see?"},
        "files": {"file": ("camera.jpg", b"\xff\xd8test\xff\xd9", "image/jpeg")},
    }
    with TestClient(app) as client:
        with client.websocket_connect(
            "/xiaozhi/v1/",
            headers=headers,
        ) as websocket:
            websocket.send_text(
                '{"type":"hello","version":1,"transport":"websocket",'
                '"features":{"mcp":false},"audio_params":{"format":"opus",'
                '"sample_rate":16000,"channels":1,"frame_duration":60}}'
            )
            assert websocket.receive_json()["type"] == "hello"

            first = client.post("/v1/vision/explain", headers=headers, **upload)
            second = client.post("/v1/vision/explain", headers=headers, **upload)
            mismatched = client.post(
                "/v1/vision/explain",
                headers={**headers, "Client-Id": "another-client"},
                **upload,
            )

    assert first.status_code == 200
    assert second.status_code == 200
    assert mismatched.status_code == 409
    assert davie.received[0][-1] is None
    assert davie.received[1][-1] == "vision-session-1"


def test_camera_explain_rejects_device_token_and_oversized_image(tmp_path) -> None:
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
            max_camera_image_bytes=4,
            camera_snapshot_dir=str(tmp_path),
        ),
        media_client=NullClient(),
        davie_client=VisionDavie(),
    )
    with TestClient(app) as client:
        request = {
            "data": {"question": "What do you see?"},
            "files": {"file": ("camera.jpg", b"12345", "image/jpeg")},
        }
        assert client.post("/v1/vision/explain", **request).status_code == 401
        response = client.post(
            "/v1/vision/explain",
            headers={"Authorization": "Bearer device-secret"},
            **request,
        )
        assert response.status_code == 413


def test_public_capabilities_and_admin_device_capabilities() -> None:
    app = create_app(
        Settings(device_token="device", davie_api_key="davie", admin_token="admin"),
        media_client=NullClient(),
        davie_client=NullClient(),
        reader_library=ReaderLibrary(),
    )
    with TestClient(app) as client:
        public = client.get("/v1/capabilities")
        assert public.status_code == 200
        assert public.json()["wake_word"] == "Davie"
        assert client.get("/v1/devices/stackchan-1/capabilities").status_code == 401
        device = client.get(
            "/v1/devices/stackchan-1/capabilities",
            headers={"Authorization": "Bearer admin"},
        )
        assert device.status_code == 200
        assert device.json()["connected"] is False


def test_reader_can_be_loaded_while_device_is_offline_and_is_persistent() -> None:
    readers = ReaderLibrary()
    app = create_app(
        Settings(device_token="device", davie_api_key="davie", admin_token="admin"),
        media_client=NullClient(),
        davie_client=NullClient(),
        reader_library=readers,
    )
    headers = {"Authorization": "Bearer admin"}
    with TestClient(app) as client:
        loaded = client.post(
            "/v1/devices/stackchan-1/reader/load",
            headers=headers,
            json={"title": "A short book", "text": "First sentence. Second sentence."},
        )
        assert loaded.status_code == 200
        assert loaded.json()["connected"] is False
        status = client.get("/v1/devices/stackchan-1/reader", headers=headers)
        assert status.json()["reader"]["segment_count"] == 2
        assert client.post(
            "/v1/devices/stackchan-1/reader/load",
            headers=headers,
            json={"title": "A short book", "text": "Text", "autoplay": True},
        ).status_code == 409
        cleared = client.delete("/v1/devices/stackchan-1/reader", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["removed"] is True
        assert cleared.json()["reader"]["segment_count"] == 0
