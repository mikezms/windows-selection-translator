"""生词本 vocab.json 的读写：原子写入，忽略大小写去重。"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VOCAB_PATH = os.path.join(SCRIPT_DIR, "vocab.json")

DEFAULT_SCORE = 50.0
SCORE_MIN = 0.0
SCORE_MAX = 100.0


def load(path: str = DEFAULT_VOCAB_PATH) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []


def save(items: list[dict], path: str = DEFAULT_VOCAB_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def item_score(it: dict) -> float:
    s = it.get("score")
    if s is None:
        v = DEFAULT_SCORE
    else:
        try:
            v = float(s)
        except (TypeError, ValueError):
            v = DEFAULT_SCORE
    return max(SCORE_MIN, min(SCORE_MAX, v))


def normalize_scores(items: list[dict]) -> None:
    for it in items:
        it["score"] = item_score(it)


def find_item(items: list[dict], word: str) -> dict | None:
    """忽略大小写+空白查词。"""
    key = (word or "").strip().lower()
    if not key:
        return None
    for it in items:
        if isinstance(it, dict) and str(it.get("word", "")).strip().lower() == key:
            return it
    return None


def contains(items: list[dict], word: str) -> bool:
    return find_item(items, word) is not None


def add(items: list[dict], word: str, meaning: str) -> bool:
    """不存在时追加新条目，返回是否新增。"""
    if not word or not meaning:
        return False
    if contains(items, word):
        return False
    items.append({
        "word": word,
        "meaning": meaning,
        "example": "",
        "example_zh": "",
        "score": DEFAULT_SCORE,
        "reviews": 0,
    })
    return True


def needs_bilingual_example(it: dict) -> bool:
    ex = it.get("example", "")
    if ex is None or not str(ex).strip():
        return True
    zh = it.get("example_zh", "")
    if zh is None or not str(zh).strip():
        return True
    return False


def count_pending_examples(items: list[dict]) -> int:
    return sum(1 for it in items if needs_bilingual_example(it))
