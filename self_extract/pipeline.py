from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from rich import print
from tqdm import tqdm

from .aggregate import AggregateResult, ExtractionRecord, aggregate_profiles
from .cache import LLMCache
from .chunker import chunk_text
from .config import Config, ExtractionTarget
from .ollama import OllamaClient
from .prompts import load_prompts
from .scan import Note, count_words, iter_markdown_files, load_note


def _coerce_item(item: Any) -> str:
    """Normalize model output into a readable string."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float)):
        return str(item)
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, dict):
        parts: List[str] = []
        for key, value in item.items():
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            label = key.replace("_", " ").strip()
            parts.append(f"{label}: {text}")
        return "; ".join(parts)
    return str(item).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return _coerce_item(value)


def _format_targets_for_prompt(targets: Sequence[ExtractionTarget]) -> str:
    lines: List[str] = []
    for target in targets:
        if target.description:
            lines.append(f"- {target.name}: {target.description}")
        else:
            lines.append(f"- {target.name}")
    if not lines:
        return ""
    return "  " + "\n  ".join(lines)


def _build_json_schema(target_names: Sequence[str]) -> str:
    if not target_names:
        return "{}"
    lines: List[str] = ["{"]
    for idx, name in enumerate(target_names):
        suffix = "," if idx < len(target_names) - 1 else ""
        lines.append(f'  "{name}": []{suffix}')
    lines.append("}")
    return "\n".join(lines)


def _normalize_entry(entry: Any) -> Optional[Dict[str, str]]:
    if isinstance(entry, dict):
        value = ""
        for candidate in (entry.get("value"), entry.get("text"), entry.get("statement")):
            text = _clean_text(candidate)
            if text:
                value = text
                break
        if not value:
            return None

        evidence_raw = entry.get("evidence") or entry.get("reason") or entry.get("support")
        if isinstance(evidence_raw, list):
            fragments = [_clean_text(item) for item in evidence_raw]
            evidence = "; ".join(fragment for fragment in fragments if fragment)
        else:
            evidence = _clean_text(evidence_raw)

        return {
            "value": value,
            "evidence": evidence,
        }

    value = _clean_text(entry)
    if not value:
        return None
    return {
        "value": value,
        "evidence": "",
    }


def _normalize_payload(data: Dict[str, Any], keys: Sequence[str], source: str) -> Dict[str, List[Dict[str, str]]]:
    normalized: Dict[str, List[Dict[str, str]]] = {}
    for key in keys:
        raw_value = data.get(key, [])
        items: List[Dict[str, str]] = []
        if isinstance(raw_value, list):
            for entry in raw_value:
                normalized_entry = _normalize_entry(entry)
                if normalized_entry:
                    normalized_entry.setdefault("evidence", "")
                    normalized_entry["governance"] = source
                    items.append(normalized_entry)
        elif raw_value:
            normalized_entry = _normalize_entry(raw_value)
            if normalized_entry:
                normalized_entry.setdefault("evidence", "")
                normalized_entry["governance"] = source
                items.append(normalized_entry)
        normalized[key] = items
    return normalized

def run_pipeline(cfg: Config) -> Dict[str, Dict[str, object]]:
    prompts = load_prompts(cfg.prompts_path)
    cache = LLMCache(cfg.cache_path)
    client = OllamaClient(cfg.ollama.base_url, cache=cache)

    records: List[ExtractionRecord] = []
    log_rows: List[Dict[str, str]] = []
    raw_extractions: List[Dict[str, object]] = []

    target_names = cfg.extraction_target_names
    targets_prompt = _format_targets_for_prompt(cfg.extraction_targets)
    json_schema = _build_json_schema(target_names)

    files = list(iter_markdown_files(cfg))
    if not files:
        raise RuntimeError(f"No markdown files found in configured inputs: {cfg.describe_inputs()}")

    iterator = tqdm(files, desc="Processing notes")
    for file_path in iterator:
        note: Note = load_note(file_path)
        text = note.content
        if count_words(text) < cfg.filters.min_word_count:
            continue

        last_edited_date: Optional[str]
        if note.last_edited:
            last_edited_date = note.last_edited.date().isoformat()
        else:
            last_edited_date = None

        chunks = chunk_text(text)
        for idx, chunk in enumerate(chunks):
            prompt = prompts.render(
                "extraction",
                EXTRACTION_TARGETS=targets_prompt,
                TEXT=chunk,
                SOURCE=str(file_path),
                JSON_SCHEMA=json_schema,
            )
            try:
                raw = client.generate(cfg.ollama.model, prompt)
                parsed = client.parse_response(raw)
            except Exception as e:
                print(
                    f"[yellow]Warning:[/yellow] Extraction failed for {file_path} chunk {idx}: {e}"
                )
                continue
            normalized = _normalize_payload(parsed, target_names, str(file_path))

            records.append(
                ExtractionRecord(
                    source=str(file_path),
                    last_edited_date=last_edited_date,
                    payload=normalized,
                )
            )

            raw_extractions.append(
                {
                    "source": str(file_path),
                    "chunk": idx,
                    "last_edited_date": last_edited_date,
                    "items": normalized,
                }
            )

            log_rows.append(
                {
                    "file": str(file_path),
                    "chunk": str(idx),
                    "last_edited_date": last_edited_date or "",
                    "items": json.dumps({k: len(v) for k, v in normalized.items()}),
                }
            )

    aggregate = aggregate_profiles(records, cfg, client, prompts)

    output_payload: Dict[str, object] = {"raw_extractions": raw_extractions}
    output_payload.update(aggregate.buckets)
    if aggregate.global_context:
        output_payload["_global_context"] = aggregate.global_context

    output_path = cfg.output_json.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    audit_path = output_path.with_suffix(".runs.jsonl")
    with audit_path.open("w", encoding="utf-8") as handle:
        for row in log_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[green]Wrote merged profile to[/green] {output_path}")
    return aggregate.buckets
