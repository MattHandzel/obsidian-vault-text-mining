"""Knowledge base loader and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import json
import math
import threading

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from .schema import get_profile_schema
from .math_utils import normalize_vector, vector_norm


@dataclass(frozen=True)
class Fact:
    """Single fact entry available to the personal context server."""

    id: str
    title: str
    summary: str
    domain: str
    tags: Tuple[str, ...]
    embedding: Tuple[float, ...]
    details: Optional[str] = None
    sensitivity_level: Optional[str] = None
    sensitivity_reasons: Tuple[str, ...] = field(default_factory=tuple)
    source: Dict[str, object] = field(default_factory=dict)
    last_updated: Optional[str] = None
    attributes: Dict[str, object] = field(default_factory=dict)

    def text_blob(self) -> str:
        """Concatenate searchable text fields."""

        pieces: List[str] = [self.title, self.summary, self.domain]
        pieces.extend(self.tags)
        if self.details:
            pieces.append(self.details)
        return " \n".join(piece for piece in pieces if piece)


class KnowledgeBase:
    """Read-only facade over `profile-all.json`. Thread-safe for reads."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._facts: List[Fact] = []
        self._index: Dict[str, Fact] = {}
        self._embeddings: List[Tuple[float, ...]] = []
        self._lock = threading.RLock()
        self.reload()

    @property
    def path(self) -> Path:
        return self._path

    def __len__(self) -> int:
        return len(self._facts)

    def iter_facts(self) -> Iterator[Fact]:
        with self._lock:
            yield from list(self._facts)

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        with self._lock:
            return self._index.get(fact_id)

    def reload(self) -> None:
        """Reload JSON from disk and rebuild indexes."""

        raw = self._path.expanduser()
        if not raw.exists():
            raise FileNotFoundError(f"Profile file not found: {self._path}")
        data = json.loads(raw.read_text(encoding="utf-8"))
        if jsonschema is not None:
            jsonschema.validate(instance=data, schema=get_profile_schema())
        facts: List[Fact] = []
        for entry in data.get("facts", []):
            try:
                fact = _fact_from_dict(entry)
            except ValueError as exc:
                raise ValueError(f"Invalid fact entry: {entry.get('id')} - {exc}") from exc
            facts.append(fact)
        embeddings = [normalize_vector(fact.embedding) for fact in facts]
        with self._lock:
            self._facts = facts
            self._index = {fact.id: fact for fact in facts}
            self._embeddings = embeddings

    def embeddings(self) -> List[Tuple[float, ...]]:
        with self._lock:
            return list(self._embeddings)

    def facts(self) -> List[Fact]:
        with self._lock:
            return list(self._facts)


def _fact_from_dict(payload: Dict[str, object]) -> Fact:
    fact_id = str(payload["id"])
    title = str(payload["title"]).strip()
    summary = str(payload.get("summary", "")).strip()
    domain = str(payload["domain"]).strip()
    tags_raw = payload.get("tags", [])
    tags: Tuple[str, ...] = tuple(str(tag).strip() for tag in tags_raw if str(tag).strip())
    embedding_raw = payload.get("embedding")
    if not isinstance(embedding_raw, list) or not embedding_raw:
        raise ValueError("fact embedding must be a non-empty list")
    embedding = tuple(float(value) for value in embedding_raw)
    sensitivity = payload.get("sensitivity") or {}
    level = sensitivity.get("level") if isinstance(sensitivity, dict) else None
    reasons = sensitivity.get("reasons") if isinstance(sensitivity, dict) else None
    reason_tuple: Tuple[str, ...] = tuple(str(reason) for reason in (reasons or []) if str(reason))
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    details = payload.get("details") if isinstance(payload.get("details"), str) else None
    last_updated = payload.get("last_updated") if isinstance(payload.get("last_updated"), str) else None
    norm = vector_norm(embedding)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("fact embedding must have non-zero finite norm")
    return Fact(
        id=fact_id,
        title=title,
        summary=summary,
        domain=domain,
        tags=tags,
        embedding=embedding,
        details=details,
        sensitivity_level=str(level) if level else None,
        sensitivity_reasons=reason_tuple,
        source=source,
        last_updated=last_updated,
        attributes=attributes,
    )
