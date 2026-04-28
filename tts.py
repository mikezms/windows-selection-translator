"""
快速 TTS 模块：Edge TTS 生成 + winmm.dll 播放，支持预缓存。
"""
import asyncio
import ctypes
import hashlib
import os
import tempfile
import threading
import time

TTS_VOICE = "en-US-JennyNeural"
TTS_CACHE_DIR = os.path.join(tempfile.gettempdir(), "snap_tts_cache")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
# 最多保留 200 个音频文件，超出时淘汰最旧的
TTS_CACHE_MAX = 200

_winmm = ctypes.windll.winmm


def _cleanup_cache() -> None:
    """启动时清理超出上限的旧缓存文件。"""
    try:
        entries = []
        for name in os.listdir(TTS_CACHE_DIR):
            if not name.endswith(".mp3"):
                continue
            p = os.path.join(TTS_CACHE_DIR, name)
            try:
                entries.append((os.path.getmtime(p), p))
            except OSError:
                continue
        if len(entries) <= TTS_CACHE_MAX:
            return
        entries.sort()  # 最旧的排前面
        for _, p in entries[: len(entries) - TTS_CACHE_MAX]:
            try:
                os.remove(p)
            except OSError:
                pass
    except Exception:
        pass


# 模块加载时异步清理一次，不阻塞启动
threading.Thread(target=_cleanup_cache, daemon=True).start()


def _cache_path(text: str) -> str:
    h = hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()[:12]
    return os.path.join(TTS_CACHE_DIR, f"{h}.mp3")


def _generate_audio(text: str) -> str | None:
    """生成音频文件，返回路径。已缓存则直接返回。"""
    path = _cache_path(text)
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return path
    try:
        import edge_tts
        async def _gen():
            c = edge_tts.Communicate(text, TTS_VOICE)
            await c.save(path)
        asyncio.run(_gen())
        return path if os.path.exists(path) else None
    except Exception:
        return None


def _play_mp3(path: str) -> None:
    """用 winmm.dll 的 mciSendString 播放 mp3，无需启动外部进程。"""
    alias = "snaptts"
    _mci(f'close {alias}')
    _mci(f'open "{path}" type mpegvideo alias {alias}')
    _mci(f'play {alias} wait')
    _mci(f'close {alias}')


def _mci(cmd: str) -> None:
    buf = ctypes.create_unicode_buffer(256)
    _winmm.mciSendStringW(cmd, buf, 255, 0)


def speak(text: str) -> None:
    """同步：生成+播放（在子线程中调用）。"""
    if not text or not text.strip():
        return
    path = _generate_audio(text)
    if path:
        _play_mp3(path)


def speak_async(text: str) -> None:
    """异步：后台线程生成+播放。"""
    threading.Thread(target=speak, args=(text,), daemon=True).start()


def precache(text: str) -> None:
    """预缓存：后台线程生成音频，不播放。"""
    if not text or not text.strip():
        return
    threading.Thread(target=_generate_audio, args=(text,), daemon=True).start()
