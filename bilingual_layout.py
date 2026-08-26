"""把完整原文和完整译文组织成便于阅读的中英对照单元。"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BilingualPair:
    original: str
    translated: str
    unit: str


def _normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_paragraphs(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    paragraphs = re.split(r"\n\s*\n+", normalized)
    return [re.sub(r"[ \t\n]+", " ", part).strip() for part in paragraphs if part.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(paragraph or "")).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def build_bilingual_pairs(original: str, translated: str) -> list[BilingualPair]:
    """仅在边界可靠时逐句配对，否则退回完整段落或全文。"""
    source_text = _normalize_text(original)
    target_text = _normalize_text(translated)
    if not source_text or not target_text:
        return [BilingualPair(source_text, target_text, "全文")]

    source_paragraphs = _split_paragraphs(source_text)
    target_paragraphs = _split_paragraphs(target_text)
    if len(source_paragraphs) != len(target_paragraphs):
        return [BilingualPair(source_text, target_text, "全文")]

    pairs: list[BilingualPair] = []
    for source_paragraph, target_paragraph in zip(source_paragraphs, target_paragraphs):
        source_sentences = _split_sentences(source_paragraph)
        target_sentences = _split_sentences(target_paragraph)
        if len(source_sentences) == len(target_sentences) and len(source_sentences) > 1:
            pairs.extend(
                BilingualPair(source_sentence, target_sentence, "句子")
                for source_sentence, target_sentence in zip(source_sentences, target_sentences)
            )
        else:
            pairs.append(BilingualPair(source_paragraph, target_paragraph, "段落"))
    return pairs
