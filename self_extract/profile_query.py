from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import json


@dataclass
class AggregatedEntry:
    bucket: str
    text: str
    last_edited_date: Optional[str]
    mentions: int
    evidence: List[str]
    governance: List[str]
    summary: str

    def matches_tokens(self, tokens: Sequence[str], require_all: bool) -> bool:
        if not tokens:
            return True
        haystack = " \n".join([
            self.bucket,
            self.text,
            " ".join(self.evidence),
            " ".join(self.governance),
            self.last_edited_date or "",
        ]).casefold()
        hits = [token in haystack for token in tokens]
        return all(hits) if require_all else any(hits)

    def within_range(
        self,
        after: Optional[date],
        before: Optional[date],
    ) -> bool:
        if not (after or before) or not self.last_edited_date:
            return True
        try:
            item_date = date.fromisoformat(self.last_edited_date)
        except ValueError:
            return True
        if after and item_date < after:
            return False
        if before and item_date > before:
            return False
        return True


@dataclass
class RawEntry:
    bucket: str
    value: str
    evidence: str
    governance: str
    source: str
    chunk: int
    last_edited_date: Optional[str]

    def matches_tokens(self, tokens: Sequence[str], require_all: bool) -> bool:
        if not tokens:
            return True
        haystack = " \n".join(
            [
                self.bucket,
                self.value,
                self.evidence,
                self.governance,
                self.source,
                str(self.chunk),
                self.last_edited_date or "",
            ]
        ).casefold()
        hits = [token in haystack for token in tokens]
        return all(hits) if require_all else any(hits)

    def within_range(
        self,
        after: Optional[date],
        before: Optional[date],
    ) -> bool:
        if not (after or before) or not self.last_edited_date:
            return True
        try:
            item_date = date.fromisoformat(self.last_edited_date)
        except ValueError:
            return True
        if after and item_date < after:
            return False
        if before and item_date > before:
            return False
        return True


def load_profile(path: Path) -> Dict[str, Any]:
    raw = path.expanduser().read_text(encoding="utf-8")
    return json.loads(raw)


def iter_aggregated_entries(profile: Dict[str, Any]) -> Iterable[AggregatedEntry]:
    for bucket, data in profile.items():
        if bucket in {"raw_extractions", "_global_context"}:
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("items", [])
        summary = data.get("summary", "")
        for item in items:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            mentions = item.get("mentions")
            try:
                mentions_count = int(mentions)
            except (TypeError, ValueError):
                mentions_count = 1
            evidence = item.get("evidence") or []
            if isinstance(evidence, str):
                evidence_list = [evidence]
            else:
                evidence_list = [str(entry).strip() for entry in evidence if str(entry).strip()]
            governance = item.get("governance") or []
            if isinstance(governance, str):
                governance_list = [governance]
            else:
                governance_list = [str(entry).strip() for entry in governance if str(entry).strip()]
            yield AggregatedEntry(
                bucket=bucket,
                text=text,
                last_edited_date=item.get("last_edited_date"),
                mentions=mentions_count,
                evidence=evidence_list,
                governance=governance_list,
                summary=summary,
            )


def iter_raw_entries(profile: Dict[str, Any]) -> Iterable[RawEntry]:
    raw_items = profile.get("raw_extractions", [])
    if not isinstance(raw_items, list):
        return
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source", "")
        chunk = entry.get("chunk", 0)
        try:
            chunk_index = int(chunk)
        except (TypeError, ValueError):
            chunk_index = 0
        last_edited = entry.get("last_edited_date")
        items = entry.get("items", {})
        if not isinstance(items, dict):
            continue
        for bucket, values in items.items():
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                text = (value.get("value") or "").strip()
                if not text:
                    continue
                yield RawEntry(
                    bucket=bucket,
                    value=text,
                    evidence=(value.get("evidence") or "").strip(),
                    governance=value.get("governance", ""),
                    source=source,
                    chunk=chunk_index,
                    last_edited_date=last_edited,
                )


def filter_aggregated(
    entries: Iterable[AggregatedEntry],
    bucket: Optional[str],
    tokens: Sequence[str],
    require_all: bool,
    after: Optional[date],
    before: Optional[date],
    min_mentions: Optional[int],
) -> List[AggregatedEntry]:
    results: List[AggregatedEntry] = []
    for entry in entries:
        if bucket and entry.bucket != bucket:
            continue
        if min_mentions and entry.mentions < min_mentions:
            continue
        if not entry.matches_tokens(tokens, require_all):
            continue
        if not entry.within_range(after, before):
            continue
        results.append(entry)
    return results


def filter_raw(
    entries: Iterable[RawEntry],
    bucket: Optional[str],
    tokens: Sequence[str],
    require_all: bool,
    after: Optional[date],
    before: Optional[date],
) -> List[RawEntry]:
    results: List[RawEntry] = []
    for entry in entries:
        if bucket and entry.bucket != bucket:
            continue
        if not entry.matches_tokens(tokens, require_all):
            continue
        if not entry.within_range(after, before):
            continue
        results.append(entry)
    return results
