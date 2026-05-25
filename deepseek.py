"""AI API：翻译与例句生成（支持 OpenAI 兼容接口和 Gemini）。"""
import json
import re
from functools import lru_cache

import requests

import app_config

_CLIENT = None
_CLIENT_KEY = None

GEMINI_TIMEOUT = (12, 40)
MODEL_TIMEOUT = (8, 20)
ARTICLE_TRANSLATE_THRESHOLD = 320


def _load_config_snapshot(config: dict | None = None) -> dict:
    if config is None:
        return dict(app_config.load_config())
    return dict(config)


def _config_text(config: dict, key: str, default: str = "") -> str:
    return str(config.get(key) or default).strip()


def _resolve_request_config(
    config: dict | None = None,
    *,
    provider_default: str = "custom",
) -> tuple[dict, str, str, str, str]:
    cfg = _load_config_snapshot(config)
    provider = _config_text(cfg, "ai_provider", provider_default)
    key = _config_text(cfg, "ai_api_key")
    base_url = app_config.effective_base_url(provider, _config_text(cfg, "ai_base_url"))
    model = _config_text(cfg, "ai_model")
    return cfg, provider, key, base_url, model


def read_api_key() -> str:
    """读取当前配置里的 API Key，保留旧函数名用于兼容。"""
    return str(app_config.load_config().get("ai_api_key") or "").strip()


def get_client():
    """懒加载 + 单例。仅 OpenAI 兼容接口返回 client；Gemini 使用 REST。"""
    global _CLIENT, _CLIENT_KEY
    _cfg, provider, key, base_url, _model = _resolve_request_config()
    if app_config.provider_kind(provider) != "openai_compatible":
        return None
    client_key = (key, base_url)
    if _CLIENT is not None and _CLIENT_KEY == client_key:
        return _CLIENT
    if not key or not base_url:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    _CLIENT = OpenAI(api_key=key, base_url=base_url)
    _CLIENT_KEY = client_key
    return _CLIENT


def reset_client_cache() -> None:
    global _CLIENT, _CLIENT_KEY
    _CLIENT = None
    _CLIENT_KEY = None
    generate_example.cache_clear()
    generate_example_and_meaning.cache_clear()
    translate_geek_mode.cache_clear()


def _current_model() -> str:
    return str(app_config.load_config().get("ai_model") or "").strip()


def _strip_model_noise(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"(?is)<think>.*?</think>", "", s).strip()
    return s


def _chat_openai_compatible(system: str, user: str, cfg: dict | None = None) -> str:
    if cfg is None:
        client = get_client()
        model = _current_model()
    else:
        _, _provider, key, base_url, model = _resolve_request_config(cfg)
        if not key or not base_url or not model:
            return ""
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base_url)
    if client is None:
        return ""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=False,
    )
    return _strip_model_noise(resp.choices[0].message.content or "")


def _chat_gemini(system: str, user: str, cfg: dict | None = None) -> str:
    cfg, _provider, key, base_url, model = _resolve_request_config(cfg, provider_default="gemini")
    if not key or not model:
        return ""
    url = f"{base_url}/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
    }
    resp = requests.post(url, headers={"x-goog-api-key": key}, json=payload, timeout=GEMINI_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return _strip_model_noise("".join(str(part.get("text") or "") for part in parts))


def _chat(system: str, user: str) -> str:
    cfg = _load_config_snapshot()
    if not app_config.is_ai_configured(cfg):
        return ""
    if app_config.provider_kind(_config_text(cfg, "ai_provider")) == "gemini":
        return _chat_gemini(system, user)
    return _chat_openai_compatible(system, user)


def test_connection(config: dict) -> tuple[bool, str]:
    """用表单配置发起一次最小请求，不保存配置。"""
    config = _load_config_snapshot(config)
    provider = _config_text(config, "ai_provider")
    if app_config.provider_kind(provider) == "openai_compatible":
        config["ai_base_url"] = app_config.effective_base_url(
            provider,
            _config_text(config, "ai_base_url"),
        )
    if not app_config.is_ai_configured(config):
        return False, "请先填写完整的服务商、模型和 API Key。"
    try:
        system = "Reply with OK only."
        user = "OK"
        if app_config.provider_kind(provider) == "gemini":
            raw = _chat_gemini(system, user, config)
        else:
            raw = _chat_openai_compatible(system, user, config)
        if raw.strip():
            return True, f"连接成功，模型返回：{raw.strip()[:80]}"
        return False, "请求成功但模型返回为空，请检查模型名称是否正确。"
    except Exception as exc:
        return False, friendly_api_error(exc)


def friendly_api_error(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    msg = str(exc)
    lower = msg.lower()
    if status == 401:
        return "API Key 无效或额度不足。"
    if status == 404:
        return "接口地址错误，请检查 Base URL（通常需要以 /v1 结尾）。"
    if status in {408, 429, 500, 502, 503, 504}:
        return "网络连接失败，请检查你的代理设置或中转服务器状态。"
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return "网络连接失败，请检查你的代理设置或中转服务器状态。"
    if "connection error" in lower or "fetch" in lower or "timed out" in lower or "timeout" in lower:
        return "网络连接失败，请检查你的代理设置或中转服务器状态。"
    return f"连接失败：{msg}"


def fetch_models(config: dict) -> tuple[bool, list[str] | str]:
    cfg = _load_config_snapshot(config)
    provider = _config_text(cfg, "ai_provider")
    key = _config_text(cfg, "ai_api_key")
    if not key:
        return False, "请先填写 API Key。"
    if app_config.provider_kind(provider) == "gemini":
        return _fetch_gemini_models(cfg)
    return _fetch_openai_compatible_models(cfg)


def _fetch_openai_compatible_models(config: dict) -> tuple[bool, list[str] | str]:
    _, provider, key, base_url, _model = _resolve_request_config(config)
    if not base_url:
        return False, "请先填写 Base URL。"
    try:
        url = base_url.rstrip("/") + "/models"
        resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=MODEL_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        models = []
        for item in data.get("data") or []:
            model_id = str(item.get("id") or "").strip()
            if model_id:
                models.append(model_id)
        return True, sorted(set(models)) if models else "接口返回为空，没有发现可用模型。"
    except Exception as exc:
        return False, friendly_api_error(exc)


def _fetch_gemini_models(config: dict) -> tuple[bool, list[str] | str]:
    _, _provider, key, base_url, _model = _resolve_request_config(config, provider_default="gemini")
    try:
        resp = requests.get(
            base_url.rstrip("/") + "/models",
            headers={"x-goog-api-key": key},
            timeout=MODEL_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        models = []
        for item in data.get("models") or []:
            name = str(item.get("name") or "").strip()
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            if name and "generateContent" in (item.get("supportedGenerationMethods") or []):
                models.append(name)
        return True, sorted(set(models)) if models else "接口返回为空，没有发现可用模型。"
    except Exception as exc:
        return False, friendly_api_error(exc)


def parse_bilingual_response(raw: str) -> tuple[str, str]:
    en, zh, _ = _parse_bilingual_response_with_meaning(raw)
    return en, zh

def _parse_bilingual_response_with_meaning(raw: str) -> tuple[str, str, str]:
    """从模型输出中解析 {'example':..., 'example_zh':..., 'meaning':...}。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        s = s[start: end + 1]
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("模型返回不是 JSON 对象")
    en = str(data.get("example", "")).strip()
    zh = str(data.get("example_zh", "")).strip()
    meaning = str(data.get("meaning", "")).strip()
    return en, zh, meaning


def is_insufficient_balance_error(exc: BaseException) -> bool:
    """DeepSeek 余额不足通常返回 HTTP 402。"""
    code = getattr(exc, "status_code", None)
    if code == 402:
        return True
    msg = str(exc).lower()
    return "insufficient balance" in msg or ("402" in msg and "balance" in msg)


def _is_article_text(text: str) -> bool:
    s = (text or "").strip()
    if len(s) >= ARTICLE_TRANSLATE_THRESHOLD:
        return True
    return s.count("\n") >= 3 or len(re.findall(r"[.!?。！？]\s+", s)) >= 4


@lru_cache(maxsize=256)
def generate_example(word: str, meaning: str) -> tuple[str, str]:
    """生成例句 + 中文翻译。失败返回 ('','')。"""
    if not app_config.is_ai_configured():
        return "", ""
    try:
        user = (
            "为英语学习者写一句自然地道的英文例句，并给出这句英文的完整简体中文翻译（整句译文，不是只翻译词条）。\n"
            f"词条（可能是词或短语）：{word}\n"
            f"词条中文释义：{meaning}\n\n"
            "只输出一个 JSON 对象，不要 markdown 代码块，不要前缀或解释。\n"
            '格式严格为：{"example":"英文例句","example_zh":"例句的完整中文翻译"}\n'
            "自然、难度适合中高级学习者；若词条是短语，请在例句中自然使用该短语。\n"
        )
        raw = _chat(
            'Reply with a single JSON object only, keys: "example" (English), "example_zh" (Chinese).',
            user,
        )
        return parse_bilingual_response(raw)
    except Exception:
        return "", ""

@lru_cache(maxsize=256)
def generate_example_and_meaning(word: str, meaning: str) -> tuple[str, str, str]:
    """生成例句、中文翻译及带词性的详细中文释义。失败返回 ('','','')。"""
    if not app_config.is_ai_configured():
        return "", "", ""
    try:
        user = (
            "为英语学习者写一句自然地道的英文例句，给出这句英文的完整简体中文翻译，并提供该词条带词性的详细中文释义。\n"
            f"词条（可能是词或短语）：{word}\n"
            f"参考翻译：{meaning}\n\n"
            "只输出一个 JSON 对象，不要 markdown 代码块，不要前缀或解释。\n"
            '格式严格为：{"example":"英文例句", "example_zh":"例句的完整中文翻译", "meaning":"带词性的准确中文释义，例如 v. 卷曲; n. 卷发"}\n'
            "自然、难度适合中高级学习者；若词条是短语，请在例句中自然使用该短语。\n"
        )
        raw = _chat(
            'Reply with a single JSON object only, keys: "example", "example_zh", "meaning".',
            user,
        )
        return _parse_bilingual_response_with_meaning(raw)
    except Exception:
        return "", "", ""
@lru_cache(maxsize=256)
def translate_geek_mode(text: str) -> str:
    """专门为前沿 AI 语境设计的极客翻译模式。"""
    if not app_config.is_ai_configured():
        return "(AI API 未配置，请先在设置中填写服务商、模型和 API Key)"
    try:
        if _is_article_text(text):
            user = (
                "请把下面的英文文章或长段落准确翻译成简体中文。\n"
                "【规则】\n"
                "1. 保留原文的段落结构，标题、列表、编号也尽量保留。\n"
                "2. 技术术语按 AI、LLM、Agent、深度学习语境准确处理；必要时在译文中保留英文术语。\n"
                "3. 不要逐句解释，不要添加总结，不要输出寒暄。\n"
                "4. 如果原文很长，优先完整翻译，不要省略关键内容。\n\n"
                f"待翻译内容：\n{text}\n\n"
                "请直接输出中文译文："
            )
        else:
            user = (
                "你是一个资深的 AI 前沿研究员。请准确翻译以下英文，紧密结合 LLM、Agent、深度学习等最前沿技术语境。\n"
                "【规则】\n"
                "1. 如果是长句/段落：请给出准确翻译后，换行并用一段话做“💡 通俗解释（说人话）”。\n"
                "2. 如果是短词/专有名词（如 Hermes, OpenCLAW, Few-shot）：请给出准确中文翻译，并换行做一句简短的“💡 技术背景说明”。\n\n"
                f"待翻译内容：\n{text}\n\n"
                "请直接输出你的翻译和解释结果（不需要任何前缀或寒暄）："
            )
        return _chat(
            'You are an expert AI researcher and translator. Provide clear, context-aware translations.',
            user,
        )
    except Exception as e:
        if is_insufficient_balance_error(e):
            return "(AI API 余额不足，请充值或更换 Key 后使用 AI 技术语境翻译)"
        return f"(AI 翻译失败: {str(e)})"
