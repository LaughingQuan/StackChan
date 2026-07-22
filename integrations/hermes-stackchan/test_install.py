from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load_install_module():
    path = HERE / "install.py"
    spec = importlib.util.spec_from_file_location("jm_stackchan_install_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_installer_is_idempotent_and_never_copies_token(tmp_path):
    module = _load_install_module()
    home = tmp_path / ".hermes"
    token = tmp_path / "admin-token"
    token.write_text("private-test-token")

    first = module.install_plugin(
        home,
        source_dir=HERE,
        base_url="http://stackchan.test:8793/",
        admin_token_file=token,
        default_device_id="stackchan-test",
        reader_allowed_roots=[tmp_path / "documents"],
    )
    second = module.install_plugin(
        home,
        source_dir=HERE,
        base_url="http://stackchan.test:8793",
        admin_token_file=token,
        default_device_id="stackchan-test",
        reader_allowed_roots=[tmp_path / "documents"],
    )

    assert first["ok"] is True
    assert second["hashes_match"] is True
    config_path = home / "stackchan.json"
    config = json.loads(config_path.read_text())
    assert config["admin_token_file"] == str(token)
    assert "private-test-token" not in config_path.read_text()
    assert not any("private-test-token" in path.read_text() for path in (home / "plugins" / "jm-stackchan").iterdir())
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

