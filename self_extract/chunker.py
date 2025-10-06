from __future__ import annotations

from typing import Iterable, List


def chunk_text(text: str, max_chars: int = 9999999999999) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end
    return chunks
