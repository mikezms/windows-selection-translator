"""用户设置读写：AI 服务商、Key、模型、翻译方式。"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit, urlunsplit

from app_paths import CONFIG_PATH, SCRIPT_DIR

PROVIDER_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "key_url": "https://platform.deepseek.com/api_keys",
        "icon": "deepseek-color.png",
        "kind": "openai_compatible",
        "official": True,
    },
    "openai": {
        "label": "OpenAI / ChatGPT API",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
        "key_url": "https://platform.openai.com/api-keys",
        "icon": "openai.png",
        "kind": "openai_compatible",
        "official": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "key_url": "https://aistudio.google.com/app/apikey",
        "icon": "gemini-color.png",
        "kind": "gemini",
        "official": True,
    },
    "mimo": {
        "label": "Xiaomi MiMo",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "",
        "models": [],
        "key_url": "",
        "icon": "xiaomimimo.png",
        "kind": "openai_compatible",
        "official": True,
    },
    "custom": {
        "label": "OpenAI 兼容中转站",
        "base_url": "",
        "model": "",
        "models": [],
        "key_url": "",
        "icon": "openrouter.png",
        "kind": "openai_compatible",
        "official": False,
    },
}

DEFAULT_HOTKEY = "alt+t"

DEFAULT_CONFIG = {
    "translate_source": "mymemory",
    "ai_provider": "deepseek",
    "ai_api_key": "",
    "ai_base_url": PROVIDER_PRESETS["deepseek"]["base_url"],
    "ai_model": PROVIDER_PRESETS["deepseek"]["model"],
    "ai_models": [],
    "hotkey": DEFAULT_HOTKEY,
    "setup_done": False,
}


def _normalize_model_history_item(item) -> dict[str, str] | None:
    if isinstance(item, dict):
        provider = str(item.get("provider") or "custom").strip() or "custom"
        base_url = str(item.get("base_url") or "").strip()
        model = str(item.get("model") or "").strip()
        api_key = str(item.get("api_key") or "").strip()
        if not model:
            return None
        if provider_kind(provider) == "openai_compatible":
            base_url = normalize_openai_base_url(base_url, provider)
        out = {"provider": provider, "base_url": base_url, "model": model}
        if api_key:
            out["api_key"] = api_key
        return out

    text = str(item).strip()
    if not text:
        return None
    return {"provider": "custom", "base_url": "", "model": text}


def _normalize_model_history_list(models) -> list[dict[str, str]]:
    if not isinstance(models, list):
        return []
    cleaned = []
    for item in models:
        normalized = _normalize_model_history_item(item)
        if normalized:
            cleaned.append(normalized)
    return cleaned


def _model_history_key(item: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(item.get("provider") or ""),
        str(item.get("base_url") or ""),
        str(item.get("model") or ""),
    )


def _legacy_api_key() -> str:
    path = os.path.join(SCRIPT_DIR, "api_key.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    return s
    except Exception:
        return ""
    return ""


def load_config() -> dict:
    data = DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass

    provider = data.get("ai_provider") or "deepseek"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])
    if provider != "custom":
        data["ai_base_url"] = data.get("ai_base_url") or preset["base_url"]
        data["ai_model"] = data.get("ai_model") or preset["model"]
    if not data.get("ai_api_key"):
        data["ai_api_key"] = _legacy_api_key()
    data["ai_models"] = _normalize_model_history_list(data.get("ai_models"))
    hotkey = str(data.get("hotkey") or DEFAULT_HOTKEY).strip().lower()
    data["hotkey"] = hotkey or DEFAULT_HOTKEY
    return data


def save_config(config: dict) -> None:
    data = DEFAULT_CONFIG.copy()
    if isinstance(config, dict):
        data.update(config)
    data["ai_models"] = _normalize_model_history_list(data.get("ai_models"))
    data["hotkey"] = normalize_hotkey(data.get("hotkey") or DEFAULT_HOTKEY)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def provider_label(provider: str) -> str:
    return PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])["label"]


def provider_kind(provider: str) -> str:
    return PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])["kind"]


def provider_preset(provider: str) -> dict:
    return PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])


def is_official_provider(provider: str) -> bool:
    return bool(provider_preset(provider).get("official"))


def provider_base_url(provider: str) -> str:
    return str(provider_preset(provider).get("base_url") or "")


def provider_models(provider: str) -> list[str]:
    return list(provider_preset(provider).get("models") or [])


def normalize_openai_base_url(base_url: str, provider: str = "custom") -> str:
    """兼容中转站常见写法：域名、/v1、/v1/chat/completions。"""
    raw = str(base_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    raw = raw.rstrip("/")

    lower = raw.lower()
    if lower.endswith("/chat/completions"):
        raw = raw[: -len("/chat/completions")].rstrip("/")

    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if provider == "custom" and not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def effective_base_url(provider: str, base_url: str = "") -> str:
    if is_official_provider(provider):
        return provider_base_url(provider)
    if provider_kind(provider) == "openai_compatible":
        return normalize_openai_base_url(base_url, provider)
    return str(base_url or "").strip().rstrip("/") or provider_base_url(provider)


def is_ai_configured(config: dict | None = None) -> bool:
    cfg = config or load_config()
    provider = cfg.get("ai_provider") or "deepseek"
    if not str(cfg.get("ai_api_key") or "").strip():
        return False
    if not str(cfg.get("ai_model") or "").strip():
        return False
    if provider_kind(provider) == "openai_compatible" and not str(cfg.get("ai_base_url") or "").strip():
        return False
    return True


def normalize_hotkey(value: str) -> str:
    """把用户输入规范成 a+b+c 形式。"""
    raw = str(value or "").strip().lower()
    if not raw:
        return DEFAULT_HOTKEY
    raw = raw.replace("＋", "+").replace(" ", "")
    raw = raw.replace("control", "ctrl").replace("option", "alt").replace("command", "cmd")
    raw = raw.replace("win", "win")
    parts = [part for part in raw.split("+") if part]
    unique = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    if not unique:
        return DEFAULT_HOTKEY
    return "+".join(unique)


def append_model_history(config: dict, provider: str, base_url: str, model: str, api_key: str = "") -> dict:
    data = dict(config or {})
    models = _normalize_model_history_list(data.get("ai_models"))
    item = _normalize_model_history_item({
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    })
    if not item:
        return data
    item_key = _model_history_key(item)
    models = [m for m in models if _model_history_key(m) != item_key]
    models.insert(0, item)
    data["ai_models"] = models[:10]
    return data


def needs_first_run_setup() -> bool:
    cfg = load_config()
    return not bool(cfg.get("setup_done")) or not is_ai_configured(cfg)
