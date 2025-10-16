"""Utilities to create profile-all.json from aggregated pipeline output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from .search import EmbeddingBackend


class ProfileBuilderError(RuntimeError):
    pass


def build_profile_database(
    aggregated_profile: Path,
    output_path: Path,
    embedding_model: str = "all-MiniLM-L6-v2",
    embedding_device: str | None = None,
) -> None:
    """Transform `output/profile.json` into `profile-all.json` with embeddings."""

    aggregated_data = json.loads(aggregated_profile.read_text(encoding="utf-8"))
    backend = EmbeddingBackend(model_name=embedding_model, device=embedding_device)
    facts: List[Dict[str, object]] = []
    for bucket, payload in aggregated_data.items():
        if bucket in {"raw_extractions", "_global_context"}:
            continue
        if not isinstance(payload, dict):
            continue
        summary = str(payload.get("summary", ""))
        for item in payload.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            fact_id = str(item.get("id") or uuid4())
            combined_text = f"{text}\n{summary}" if summary else text
            embedding = backend.encode(combined_text)
            governance = item.get("governance") or []
            tags: List[str] = [bucket]
            if isinstance(governance, list):
                tags.extend(str(value).strip() for value in governance if str(value).strip())
            evidence = item.get("evidence") or []
            attributes: Dict[str, object] = {
                "mentions": item.get("mentions", 1),
                "evidence": evidence,
            }
            sensitivity_level = "public"
            lower_tags = {tag.lower() for tag in tags}
            if {"private", "personal", "medical"}.intersection(lower_tags):
                sensitivity_level = "personal"
            fact = {
                "id": fact_id,
                "title": text.split(". ")[0][:120] or text[:120],
                "summary": text,
                "details": summary,
                "domain": bucket,
                "tags": list(dict.fromkeys(tags)),
                "sensitivity": {"level": sensitivity_level, "reasons": list(lower_tags)},
                "source": {
                    "bucket": bucket,
                    "mentions": item.get("mentions", 1),
                },
                "last_updated": item.get("last_edited_date"),
                "embedding": list(embedding),
                "attributes": attributes,
            }
            facts.append(fact)
    if not facts:
        raise ProfileBuilderError("No facts extracted from aggregated profile")
    payload = {
        "metadata": {
            "version": "1.0",
            "source": str(aggregated_profile),
        },
        "facts": facts,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
