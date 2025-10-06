from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import numpy as np

from .config import Config
from .ollama import OllamaClient
from .prompts import Prompts
from rich import print


@dataclass
class ExtractionRecord:
    source: str
    last_edited_date: Optional[str]
    payload: Dict[str, List[Dict[str, Any]]]


@dataclass
class AggregateResult:
    buckets: Dict[str, Dict[str, object]]
    global_context: Optional[str]


_DROP_TERMS = ("unknown", "not specified", "n/a", "none", "null")


def _clean_value(value: str) -> Optional[str]:
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if any(term in lowered for term in _DROP_TERMS):
        return None
    return text


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result = [_stringify(item) for item in value]
    else:
        result = [_stringify(value)]
    return [item for item in result if item]


def _merge_lists(existing: List[str], additions: Iterable[str]) -> List[str]:
    merged = list(existing)
    seen: Set[str] = set(existing)
    for item in additions:
        if item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return merged


def _collect_support(items: Sequence[Dict[str, Any]], field: str) -> List[str]:
    collected: List[str] = []
    seen: Set[str] = set()
    for item in items:
        raw = item.get(field)
        values = _as_list(raw)
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            collected.append(value)
    return collected


def _serialize_items(records: Sequence[ExtractionRecord], bucket: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for record in records:
        values = record.payload.get(bucket, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict):
                text_candidate = value.get("value") or value.get("text")
                cleaned = _clean_value(_stringify(text_candidate))
                evidence = _as_list(value.get("evidence"))
                governance = _as_list(value.get("governance"))
            else:
                cleaned = _clean_value(_stringify(value))
                evidence = []
                governance = []
            if not cleaned:
                continue
            if not governance:
                governance = [record.source]
            else:
                governance = _merge_lists(governance, [record.source])
            items.append(
                {
                    "value": cleaned,
                    "last_edited_date": record.last_edited_date,
                    "source": record.source,
                    "evidence": evidence,
                    "governance": governance,
                }
            )
    return items


def _latest_created(items: Sequence[Dict[str, Any]]) -> Optional[str]:
    best: Optional[str] = None
    for entry in items:
        created = entry.get("last_edited_date")
        if not created:
            continue
        if best is None or created > best:
            best = created
    return best


def _fallback_merge(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return []

    combined: Dict[str, Dict[str, Any]] = {}
    for entry in items:
        raw_value = entry.get("value")
        text = _stringify(raw_value)
        if not text:
            continue
        key = text.casefold()
        bucket = combined.setdefault(
            key,
            {
                "text": text,
                "last_edited_date": entry.get("last_edited_date"),
                "mentions": 0,
                "evidence": [],
                "governance": [],
            },
        )
        bucket["mentions"] += 1
        date = entry.get("last_edited_date")
        if date and ((bucket.get("last_edited_date") or "") < date):
            bucket["last_edited_date"] = date
        bucket["evidence"] = _merge_lists(bucket["evidence"], _as_list(entry.get("evidence")))
        bucket["governance"] = _merge_lists(bucket["governance"], _as_list(entry.get("governance")))

    result = list(combined.values())
    result.sort(key=lambda entry: (entry.get("last_edited_date") or "", entry["text"]), reverse=True)
    return result


def _batch(seq: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for idx in range(0, len(seq), size):
        yield seq[idx : idx + size]


def _embed_texts(
    texts: Sequence[str],
    client: OllamaClient,
    model: str,
    batch_size: int,
) -> np.ndarray:
    vectors: List[List[float]] = []
    for chunk in _batch(list(texts), max(1, batch_size)):
        vectors.extend(client.embeddings(model=model, texts=chunk))
    return np.asarray(vectors, dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if not denom:
        return 0.0
    return float(np.dot(a, b) / denom)


def _cluster_indices(vectors: np.ndarray, threshold: float) -> List[List[int]]:
    if not len(vectors):
        return []
    clusters: List[List[int]] = []
    centroids: List[np.ndarray] = []
    for idx, vec in enumerate(vectors):
        assigned = False
        best_idx = -1
        best_sim = threshold
        for c_idx, centroid in enumerate(centroids):
            sim = _cosine(vec, centroid)
            if sim >= best_sim:
                best_sim = sim
                best_idx = c_idx
        if best_idx >= 0:
            clusters[best_idx].append(idx)
            size = len(clusters[best_idx])
            centroids[best_idx] = (centroids[best_idx] * (size - 1) + vec) / size
            assigned = True
        if not assigned:
            clusters.append([idx])
            centroids.append(vec.copy())
    return clusters


def _context_section(context: Optional[str]) -> str:
    if context:
        return f"Global context:\n{context}\n"
    return ""


def _aggregate_cluster(
    bucket: str,
    cluster_items: List[Dict[str, Any]],
    client: OllamaClient,
    model: str,
    prompts: Prompts,
    pass_index: int,
    context: Optional[str],
) -> Dict[str, Any]:
    latest = _latest_created(cluster_items)
    payload = json.dumps(cluster_items, ensure_ascii=False)
    prompt = prompts.render(
        "cluster",
        BUCKET=bucket,
        PASS=str(pass_index + 1),
        CONTEXT_SECTION=_context_section(context),
        ENTRIES=payload,
    )

    try:
        raw = client.generate(model=model, prompt=prompt)
        data = client.parse_response(raw)
    except Exception as e:
        print(
            f"[yellow]Warning:[/yellow] Cluster aggregation failed for bucket '{bucket}' pass {pass_index+1}: {e}"
        )
        data = None

    if isinstance(data, dict):
        text = (data.get("text") or data.get("value") or "").strip()
        created = data.get("last_edited_date") or data.get("date") or latest
        if text:
            return {"text": text, "last_edited_date": created}

    fallback = max(
        (item for item in cluster_items if item.get("value")),
        key=lambda entry: (entry.get("last_edited_date") or "", entry["value"]),
        default=None,
    )
    if not fallback:
        return {"text": "", "last_edited_date": latest}
    return {"text": fallback["value"], "last_edited_date": fallback.get("last_edited_date") or latest}


def _dedupe_sorted(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    combined: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        text = _stringify(entry.get("text"))
        if not text:
            continue
        key = text.casefold()
        mentions = entry.get("mentions")
        mentions_count = mentions if isinstance(mentions, int) and mentions > 0 else 1
        evidence = _collect_support([entry], "evidence")
        governance = _collect_support([entry], "governance")
        date = entry.get("last_edited_date")

        existing = combined.get(key)
        if existing:
            existing["mentions"] += mentions_count
            existing["evidence"] = _merge_lists(existing["evidence"], evidence)
            existing["governance"] = _merge_lists(existing["governance"], governance)
            if date and ((existing.get("last_edited_date") or "") < date):
                existing["last_edited_date"] = date
        else:
            combined[key] = {
                "text": text,
                "last_edited_date": date,
                "mentions": mentions_count,
                "evidence": evidence,
                "governance": governance,
            }

    deduped = list(combined.values())
    deduped.sort(
        key=lambda entry: (entry.get("last_edited_date") or "", entry["text"]),
        reverse=True,
    )
    return deduped


def _summarize_bucket(
    bucket: str,
    items: List[Dict[str, Any]],
    client: OllamaClient,
    model: str,
    prompts: Prompts,
    limit: int,
    pass_index: int,
    context: Optional[str],
) -> str:
    if not items:
        return ""
    excerpt = items[:limit]
    payload = json.dumps(excerpt, ensure_ascii=False)
    prompt = prompts.render(
        "summary",
        BUCKET=bucket,
        PASS=str(pass_index + 1),
        CONTEXT_SECTION=_context_section(context),
        FACTS=payload,
    )

    try:
        raw = client.generate(model=model, prompt=prompt)
        data = client.parse_response(raw)
        summary = ""
        if isinstance(data, dict):
            summary = (data.get("summary") or data.get("text") or "").strip()
        elif isinstance(data, str):
            summary = data.strip()
        if summary:
            return summary
    except Exception as e:
        print(
            f"[yellow]Warning:[/yellow] Summary generation failed for bucket '{bucket}' pass {pass_index+1}: {e}"
        )

    bullets = [f"- {entry['text']}" for entry in excerpt if entry.get("text")]
    return "\n".join(bullets)


def _records_from_aggregated(aggregated: Dict[str, Dict[str, object]]) -> List[ExtractionRecord]:
    records: List[ExtractionRecord] = []
    for bucket, data in aggregated.items():
        items = data.get("items", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            created = entry.get("last_edited_date") or None
            governance = _as_list(entry.get("governance")) or [f"aggregate_pass:{bucket}"]
            payload_entry = {
                "value": text,
                "evidence": _as_list(entry.get("evidence")),
                "governance": governance,
            }
            records.append(
                ExtractionRecord(
                    source=f"aggregate_pass:{bucket}",
                    last_edited_date=created,
                    payload={bucket: [payload_entry]},
                )
            )
    return records


def _build_global_context(
    aggregated: Dict[str, Dict[str, object]],
    client: OllamaClient,
    prompts: Prompts,
    model: str,
) -> Optional[str]:
    payload = json.dumps(aggregated, ensure_ascii=False)
    prompt = prompts.render("global_context", CANONICAL=payload)
    try:
        raw = client.generate(model=model, prompt=prompt)
        data = client.parse_response(raw)
        if isinstance(data, dict):
            context = (data.get("context") or data.get("summary") or "").strip()
            if context:
                return context
        elif isinstance(data, str):
            context = data.strip()
            if context:
                return context
    except Exception as e:
        print(f"[yellow]Warning:[/yellow] Global context generation failed: {e}")

    fragments: List[str] = []
    for bucket, data in aggregated.items():
        if not isinstance(data, dict):
            continue
        summary = (data.get("summary") or "").strip()
        if summary:
            fragments.append(f"{bucket}: {summary}")
        else:
            items = data.get("items", [])
            if isinstance(items, list):
                for entry in items[:3]:
                    text = (entry.get("text") or "").strip() if isinstance(entry, dict) else ""
                    if text:
                        fragments.append(f"{bucket}: {text}")
    return "\n".join(fragments) if fragments else None


def _build_passthrough(
    records: Sequence[ExtractionRecord],
    targets: Sequence[str],
) -> Dict[str, Dict[str, object]]:
    buckets: Dict[str, Dict[str, object]] = {}
    for bucket in targets:
        raw_items = _serialize_items(records, bucket)
        items: List[Dict[str, Any]] = []
        for raw in raw_items:
            items.append(
                {
                    "text": raw["value"],
                    "last_edited_date": raw.get("last_edited_date"),
                    "mentions": 1,
                    "evidence": list(raw.get("evidence", [])),
                    "governance": list(raw.get("governance", [])),
                }
            )
        buckets[bucket] = {"items": items, "summary": ""}
    return buckets


def aggregate_profiles(
    records: Sequence[ExtractionRecord],
    cfg: Config,
    client: OllamaClient,
    prompts: Prompts,
) -> AggregateResult:
    target_names = cfg.extraction_target_names

    if not cfg.aggregation.enabled or cfg.aggregation.passes <= 0:
        buckets = _build_passthrough(records, target_names)
        return AggregateResult(buckets=buckets, global_context=None)

    passes = max(1, cfg.aggregation.passes)
    primary_model = cfg.ollama.model
    model = getattr(cfg.ollama, "aggregator_model", None) or primary_model
    if model != primary_model:
        try:
            if not client.model_exists(model):
                print(
                    f"[yellow]Warning:[/yellow] Ollama model '{model}' was not found; falling back to '{primary_model}' for aggregation."
                )
                model = primary_model
        except RuntimeError as exc:
            print(
                f"[yellow]Warning:[/yellow] Could not verify Ollama model '{model}' ({exc}); continuing without fallback."
            )
    embedding_model = getattr(cfg.ollama, "embedding_model", None)
    threshold = cfg.aggregation.similarity_threshold
    batch_size = cfg.aggregation.embedding_batch_size
    clustering_enabled = cfg.aggregation.enable_clustering and bool(embedding_model)

    global_context: Optional[str] = None
    current_records: Sequence[ExtractionRecord] = records
    aggregated: Dict[str, Dict[str, object]] = {}

    for pass_index in range(passes):
        aggregated = {}
        for bucket in target_names:
            raw_items = _serialize_items(current_records, bucket)
            if not raw_items:
                aggregated[bucket] = {"items": [], "summary": ""}
                continue

            if clustering_enabled:
                try:
                    vectors = _embed_texts(
                        [item["value"] or "" for item in raw_items],
                        client=client,
                        model=embedding_model,
                        batch_size=batch_size,
                    )
                    clusters_idx = _cluster_indices(vectors, threshold)
                except Exception as e:
                    print(
                        f"[yellow]Warning:[/yellow] Embedding/cluster step failed for bucket '{bucket}': {e}"
                    )
                    clusters_idx = []
            else:
                clusters_idx = []

            if not clusters_idx:
                clusters_idx = [[i] for i in range(len(raw_items))]

            canonical_items: List[Dict[str, Any]] = []
            for indices in clusters_idx:
                cluster = [raw_items[i] for i in indices]
                canonical = _aggregate_cluster(
                    bucket,
                    cluster,
                    client,
                    model,
                    prompts,
                    pass_index,
                    global_context,
                )
                if canonical.get("text"):
                    canonical["mentions"] = len(cluster)
                    canonical["evidence"] = _collect_support(cluster, "evidence")
                    canonical["governance"] = _collect_support(cluster, "governance")
                    canonical_items.append(canonical)

            if canonical_items:
                canonical_items.sort(
                    key=lambda entry: (entry.get("last_edited_date") or "", entry["text"]),
                    reverse=True,
                )
                canonical_items = _dedupe_sorted(canonical_items)
            else:
                canonical_items = _dedupe_sorted(_fallback_merge(raw_items))

            summary = _summarize_bucket(
                bucket,
                canonical_items,
                client,
                model,
                prompts,
                cfg.aggregation.summary_max_items,
                pass_index,
                global_context,
            )
            aggregated[bucket] = {"items": canonical_items, "summary": summary}

        if cfg.aggregation.global_context and global_context is None:
            global_context = _build_global_context(aggregated, client, prompts, model)

        if pass_index < passes - 1:
            current_records = _records_from_aggregated(aggregated)

    return AggregateResult(buckets=aggregated, global_context=global_context)
