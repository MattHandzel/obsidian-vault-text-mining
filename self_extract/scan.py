from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

import frontmatter

from .config import Config


@dataclass
class Note:
    path: Path
    metadata: dict
    content: str
    last_edited: Optional[datetime]


def iter_markdown_files(cfg: Config) -> Iterable[Path]:
    inputs = cfg.resolved_inputs
    if not inputs:
        raise FileNotFoundError("No input paths configured")

    collected: List[Path] = []
    for base in inputs:
        if not base.exists():
            raise FileNotFoundError(f"Input path does not exist: {base}")
        if base.is_dir():
            collected.extend(p for p in base.rglob("*") if p.is_file())
        else:
            collected.append(base)

    files = sorted({path.resolve() for path in collected})
    seen = 0
    for path in files:
        if cfg.filters.file_extensions and path.suffix.lower() not in cfg.filters.file_extensions:
            continue
        yield path
        seen += 1
        if cfg.filters.max_files and seen >= cfg.filters.max_files:
            break


def _parse_date(value: str) -> Optional[datetime]:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y/%m/%d", "%Y %m %d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_last_edited(metadata: dict) -> Optional[datetime]:
    candidates = [
        metadata.get("last_edited_date"),
        metadata.get("last_edited_at"),
        metadata.get("last_edited"),
        metadata.get("last_modified"),
        metadata.get("modified_at"),
        metadata.get("modified"),
        metadata.get("updated_at"),
        metadata.get("updated"),
        metadata.get("created_at"),
        metadata.get("created_date"),
        metadata.get("created"),
        metadata.get("date"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            candidate = candidate[0]
        if isinstance(candidate, str):
            parsed = _parse_date(candidate)
            if parsed:
                return parsed
    return None


def load_note(path: Path) -> Note:
    post = frontmatter.load(path)
    last_edited = _extract_last_edited(post.metadata if post.metadata else {})
    return Note(path=path, metadata=post.metadata or {}, content=post.content, last_edited=last_edited)


def count_words(text: str) -> int:
    return len(text.split())
