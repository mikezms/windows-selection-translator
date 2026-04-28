"""翻译引擎：Google gtx + MyMemory，带 LRU 缓存和重试。"""
import json
import re
import time
from functools import lru_cache
from urllib.parse import quote

import requests

TRANSLATE_RETRIES = 3
TRANSLATE_TIMEOUT = (12, 30)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SnapTranslate/1.0",
}


@lru_cache(maxsize=2048)
def translate_google_gtx(text: str) -> str:
    """Google 公开 gtx 接口，质量较好，国内常需代理。"""
    encoded = quote(text)
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=zh-CN&dt=t&q={encoded}"
    )
    for attempt in range(TRANSLATE_RETRIES):
        try:
            resp = requests.get(url, timeout=TRANSLATE_TIMEOUT, headers=HTTP_HEADERS)
            resp.raise_for_status()
            data = json.loads(resp.text)
            translated = "".join(part[0] for part in data[0] if part and part[0])
            return translated.strip() if translated.strip() else "(无翻译结果)"
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt + 1 < TRANSLATE_RETRIES:
                time.sleep(0.75 * (attempt + 1))
                continue
            raise


def _mymemory_parse(resp: requests.Response) -> str:
    data = resp.json()
    block = data.get("responseData") or {}
    out = (block.get("translatedText") or "").strip()
    if not out:
        return ""
    upper = out.upper()
    if "MYMEMORY WARNING" in upper or ("QUOTA" in upper and "EXCEED" in upper):
        raise RuntimeError(out)
    return out


def _mymemory_langpairs(text: str) -> tuple[str, ...]:
    if re.search(r"[A-Za-z]", text):
        return ("en|zh-CN", "Autodetect|zh-CN")
    return ("Autodetect|zh-CN", "en|zh-CN")


@lru_cache(maxsize=2048)
def translate_mymemory(text: str) -> str:
    """MyMemory 免费接口，国内多数网络可直连。有每日免费额度。"""
    for langpair in _mymemory_langpairs(text):
        for attempt in range(TRANSLATE_RETRIES):
            try:
                resp = requests.get(
                    "https://api.mymemory.translated.net/get",
                    params={"q": text, "langpair": langpair},
                    timeout=TRANSLATE_TIMEOUT,
                    headers=HTTP_HEADERS,
                )
                resp.raise_for_status()
                out = _mymemory_parse(resp)
                if out:
                    return out
                break
            except RuntimeError:
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt + 1 < TRANSLATE_RETRIES:
                    time.sleep(0.75 * (attempt + 1))
                    continue
                break
            except requests.exceptions.HTTPError:
                break
            except (json.JSONDecodeError, KeyError, ValueError):
                break
    return "(无翻译结果)"


def translate(text: str, source: str = "mymemory") -> str:
    """统一入口：source ∈ {'mymemory', 'google', 'deepseek'}。"""
    if source == "deepseek":
        import deepseek
        return deepseek.translate_geek_mode(text)
    if source == "mymemory":
        return translate_mymemory(text)
    return translate_google_gtx(text)
