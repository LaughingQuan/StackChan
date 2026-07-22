"""Install the jm-stackchan plugin without modifying Hermes source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Iterable


PLUGIN_FILES = ("plugin.yaml", "__init__.py", "stackchan_client.py")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_plugin(
    hermes_home: Path,
    *,
    source_dir: Path,
    base_url: str,
    admin_token_file: Path,
    default_device_id: str = "",
    reader_allowed_roots: Iterable[Path] = (),
) -> dict:
    hermes_home = hermes_home.expanduser().resolve()
    target = hermes_home / "plugins" / "jm-stackchan"
    target.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        source = source_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"missing plugin source: {name}")
        temporary = target / f".{name}.tmp"
        shutil.copy2(source, temporary)
        os.replace(temporary, target / name)

    config_path = hermes_home / "stackchan.json"
    try:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    if not isinstance(existing, dict):
        raise ValueError("existing stackchan.json must be an object")
    roots = list(reader_allowed_roots) or [
        hermes_home.parent / "Documents",
        hermes_home.parent / "Downloads",
        hermes_home.parent / "NAS",
    ]
    existing.update(
        {
            "enabled": True,
            "base_url": base_url.rstrip("/"),
            "admin_token_file": str(admin_token_file.expanduser().resolve()),
            "default_device_id": default_device_id,
            "timeout_seconds": existing.get("timeout_seconds", 4.0),
            "reader_allowed_roots": [str(path.expanduser().resolve()) for path in roots],
        }
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_config = config_path.with_name(f".{config_path.name}.tmp")
    temporary_config.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n")
    os.chmod(temporary_config, 0o600)
    os.replace(temporary_config, config_path)

    source_hashes = {name: _digest(source_dir / name) for name in PLUGIN_FILES}
    installed_hashes = {name: _digest(target / name) for name in PLUGIN_FILES}
    return {
        "ok": source_hashes == installed_hashes,
        "plugin_dir": str(target),
        "config_path": str(config_path),
        "files": len(PLUGIN_FILES),
        "hashes_match": source_hashes == installed_hashes,
        "admin_token_file_exists": admin_token_file.expanduser().is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-token-file", type=Path, required=True)
    parser.add_argument("--default-device-id", default="")
    parser.add_argument("--reader-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = install_plugin(
        args.hermes_home,
        source_dir=Path(__file__).resolve().parent,
        base_url=args.base_url,
        admin_token_file=args.admin_token_file,
        default_device_id=args.default_device_id,
        reader_allowed_roots=args.reader_root,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

