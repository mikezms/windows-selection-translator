"""DeepSeek API：生成英文例句 + 中文翻译（共用单例 client + LRU 缓存）。"""
import json
import os
import re
from functools import lru_cache

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_FILE = os.path.join(SCRIPT_DIR, "api_key.txt")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

_CLIENT = None


def read_api_key() -> str:
    """从 api_key.txt 读取第一行非空内容作为 key。"""
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    return s
    except Exception:
        return ""
    return ""


def get_client():
    """懒加载 + 单例。没 key / 没装 openai 时返回 None。"""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    key = read_api_key()
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    _CLIENT = OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL)
    return _CLIENT


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


@lru_cache(maxsize=256)
def generate_example(word: str, meaning: str) -> tuple[str, str]:
    """生成例句 + 中文翻译。失败返回 ('','')。"""
    client = get_client()
    if client is None:
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
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": 'Reply with a single JSON object only, keys: "example" (English), "example_zh" (Chinese).'},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return parse_bilingual_response(raw)
    except Exception:
        return "", ""

@lru_cache(maxsize=256)
def generate_example_and_meaning(word: str, meaning: str) -> tuple[str, str, str]:
    """生成例句、中文翻译及带词性的详细中文释义。失败返回 ('','','')。"""
    client = get_client()
    if client is None:
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
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": 'Reply with a single JSON object only, keys: "example", "example_zh", "meaning".'},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _parse_bilingual_response_with_meaning(raw)
    except Exception:
        return "", "", ""
@lru_cache(maxsize=256)
def translate_geek_mode(text: str) -> str:
    """专门为前沿 AI 语境设计的极客翻译模式。"""
    client = get_client()
    if client is None:
        return "(DeepSeek API 未配置，请先在 api_key.txt 中填入您的 Key)"
    try:
        user = (
            "你是一个资深的 AI 前沿研究员。请准确翻译以下英文，紧密结合 LLM、Agent、深度学习等最前沿技术语境。\n"
            "【规则】\n"
            "1. 如果是长句/段落：请给出准确翻译后，换行并用一段话做“💡 通俗解释（说人话）”。\n"
            "2. 如果是短词/专有名词（如 Hermes, OpenCLAW, Few-shot）：请给出准确中文翻译，并换行做一句简短的“💡 技术背景说明”。\n\n"
            f"待翻译内容：\n{text}\n\n"
            "请直接输出你的翻译和解释结果（不需要任何前缀或寒暄）："
        )
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": 'You are an expert AI researcher and translator. Provide clear, context-aware translations.'},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        if is_insufficient_balance_error(e):
            return "(DeepSeek API 余额不足，请充值后使用极客翻译模式)"
        return f"(AI 翻译失败: {str(e)})"
