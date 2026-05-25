"""启动时检查新版本，并支持应用内下载安装包。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import sys
from pathlib import Path
import re
import subprocess
import tempfile
import threading

import requests

from version import APP_VERSION, UPDATE_URL

UPDATE_TIMEOUT = (4, 8)
DOWNLOAD_TIMEOUT = (6, 30)
DOWNLOAD_DIR = "SnapTranslateUpdate"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    notes: str = ""
    sha256: str = ""
    size: int = 0


def _parse_version(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(version or ""))
    return tuple(int(part) for part in parts) if parts else (0,)


def is_newer_version(remote: str, current: str = APP_VERSION) -> bool:
    left = _parse_version(remote)
    right = _parse_version(current)
    n = max(len(left), len(right))
    return left + (0,) * (n - len(left)) > right + (0,) * (n - len(right))


def _normalize_notes(notes) -> str:
    if isinstance(notes, list):
        return "\n".join(f"- {str(item)}" for item in notes)
    if isinstance(notes, dict):
        return json.dumps(notes, ensure_ascii=False, indent=2)
    return str(notes or "")


def check_update() -> UpdateInfo | None:
    resp = requests.get(UPDATE_URL, timeout=UPDATE_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return None

    version = str(data.get("version") or "").strip()
    download_url = str(data.get("download_url") or "").strip()
    if not version or not download_url:
        return None
    if not is_newer_version(version):
        return None

    size = data.get("size") or 0
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 0

    return UpdateInfo(
        version=version,
        download_url=download_url,
        notes=_normalize_notes(data.get("notes", "")).strip(),
        sha256=str(data.get("sha256") or "").strip().lower(),
        size=max(0, size),
    )


def _installer_path(version: str) -> Path:
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", version or "latest")
    folder = Path(tempfile.gettempdir()) / DOWNLOAD_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"SnapTranslateSetup-{safe_version}.exe"


def download_update(
    update: UpdateInfo,
    progress_cb=None,
    stop_event: threading.Event | None = None,
) -> Path:
    """下载更新安装包，progress_cb(downloaded, total) 会在下载过程中被调用。"""
    local_path = _installer_path(update.version)
    temp_path = local_path.with_suffix(local_path.suffix + ".download")
    downloaded = 0
    hasher = hashlib.sha256()

    with requests.get(update.download_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
        resp.raise_for_status()
        header_total = resp.headers.get("Content-Length")
        total = update.size
        if header_total:
            try:
                total = int(header_total)
            except ValueError:
                total = update.size

        with temp_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if stop_event and stop_event.is_set():
                    raise RuntimeError("下载已取消")
                if not chunk:
                    continue
                fh.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)

    if update.sha256 and hasher.hexdigest().lower() != update.sha256:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise RuntimeError("安装包校验失败，请稍后重试")

    os.replace(temp_path, local_path)
    if progress_cb:
        progress_cb(downloaded, downloaded)
    return local_path


def launch_installer(path: str | os.PathLike) -> None:
    args = [str(path)]
    if getattr(sys, "frozen", False):
        install_dir = str(Path(sys.executable).resolve().parent)
        args.append(f"/DIR={install_dir}")
    args = [
        *args,
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NOCANCEL",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/RESTARTAPPLICATIONS",
    ]
    subprocess.Popen(args, close_fds=True)
