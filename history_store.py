"""翻译历史 history.json 的读写。"""
import json
import os

from app_paths import HISTORY_PATH

DEFAULT_HISTORY_PATH = HISTORY_PATH

def load(path: str = DEFAULT_HISTORY_PATH) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []

def save(items: list[dict], path: str = DEFAULT_HISTORY_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def add(items: list[dict], ts: str, original: str, translated: str, max_items: int = 100) -> None:
    """添加一条历史记录，保持列表不超过 max_items。"""
    items.append({
        "timestamp": ts,
        "original": original,
        "translated": translated
    })
    # 保留最近的 max_items 条记录
    if len(items) > max_items:
        del items[:-max_items]

def clear(items: list[dict]) -> None:
    items.clear()
