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
        summary = str(payload.get("summary", "")).strip()
        for item in payload.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            fact_id = str(item.get("id") or uuid4())
            # Build an embedding prompt that stays focused on the fact itself.
            # Bucket-level summaries often introduce unrelated bullet lists, so we avoid
            # concatenating them into every fact. Include supporting evidence when present.
            evidence = item.get("evidence") or []
            if isinstance(evidence, list):
                evidence_text = "\n".join(str(ev).strip() for ev in evidence if str(ev).strip())
            else:
                evidence_text = str(evidence).strip()
            if evidence_text and summary and evidence_text.strip() == summary:
                # Ignore bucket-level summary mistakenly attached as evidence.
                evidence_text = ""
            combined_parts = [text]
            if evidence_text:
                combined_parts.append(evidence_text)
            item_summary = str(item.get("summary", "")).strip()
            if item_summary:
                combined_parts.append(item_summary)
            combined_text = "\n".join(part for part in combined_parts if part)
            embedding = backend.encode(combined_text)
            governance = item.get("governance") or []
            tags: List[str] = [bucket]
            if isinstance(governance, list):
                tags.extend(str(value).strip() for value in governance if str(value).strip())
            # Compose a human-readable details string from evidence items.
            attributes: Dict[str, object] = {
                "mentions": item.get("mentions", 1),
                "evidence": evidence,
            }
            sensitivity_level = "public"
            lower_tags = {tag.lower() for tag in tags}
            if {"private", "personal", "medical"}.intersection(lower_tags):
                sensitivity_level = "personal"
            fact: Dict[str, object] = {
                "id": fact_id,
                "title": text.split(". ")[0][:120] or text[:120],
                # Summary intentionally omitted in v1; the fact text is captured in title.
                # Downstream loader tolerates missing summary.
                "details": evidence_text or item_summary,
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
