from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class LLMCache:
    path: Path
    _store: Dict[str, str] = field(default_factory=dict, init=False)
    _dirty: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        path = self.path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8")
                if raw.strip():
                    self._store = json.loads(raw)
            except Exception:
                # Corrupted cache; start fresh
                self._store = {}
        else:
            self._store = {}

    @staticmethod
    def _make_key(model: str, prompt: str) -> str:
        digest = hashlib.sha256()
        digest.update(model.encode("utf-8"))
        digest.update(b"\0")
        digest.update(prompt.encode("utf-8"))
        return digest.hexdigest()

    def get(self, model: str, prompt: str) -> Optional[str]:
        key = self._make_key(model, prompt)
        return self._store.get(key)

    def set(self, model: str, prompt: str, response: str) -> None:
        key = self._make_key(model, prompt)
        if self._store.get(key) == response:
            return
        self._store[key] = response
        self._dirty = True
        self._flush()

    def _flush(self) -> None:
        if not self._dirty:
            return
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._store, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.path)
        self._dirty = False

    def clear(self) -> None:
        self._store.clear()
        self._dirty = True
        self._flush()
