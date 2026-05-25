"""应用路径：区分程序资源目录与用户可写数据目录。"""
from __future__ import annotations

import json
import os
import shutil
import sys

APP_NAME = "SnapTranslate"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """返回随程序发布的资源路径，兼容 PyInstaller。"""
    base = getattr(sys, "_MEIPASS", SCRIPT_DIR)
    return os.path.join(base, name)


def data_dir() -> str:
    """返回用户可写数据目录。"""
    override = os.environ.get("SNAPTRANSLATE_DATA_DIR")
    if override:
        path = override
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            path = os.path.join(appdata, APP_NAME)
        else:
            path = os.path.join(os.path.expanduser("~"), f".{APP_NAME}")
    os.makedirs(path, exist_ok=True)
    return path


def user_data_path(name: str) -> str:
    return os.path.join(data_dir(), name)


def ensure_json_file(name: str, default_value) -> str:
    """确保用户数据目录里有 JSON 文件；首次运行时尽量迁移项目目录旧文件。"""
    dest = user_data_path(name)
    if os.path.exists(dest):
        return dest

    legacy = os.path.join(SCRIPT_DIR, name)
    if os.path.exists(legacy):
        try:
            shutil.copy2(legacy, dest)
            return dest
        except Exception:
            pass

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(default_value, f, ensure_ascii=False, indent=2)
    return dest


VOCAB_PATH = ensure_json_file("vocab.json", [])
HISTORY_PATH = ensure_json_file("history.json", [])
CONFIG_PATH = user_data_path("settings.json")
