"""Search utilities for the personal context server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - optional dependency
    fuzz = None
    process = None

from .data import Fact, KnowledgeBase
from .math_utils import (
    argsort_desc,
    deterministic_embedding,
    matrix_dot_vector,
    normalize_vector,
)

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None


@dataclass
class SearchRequest:
    query: str
    top_k: int = 10
    fuzzy_threshold: int = 80
    semantic_weight: float = 1.0
    fuzzy_weight: float = 0.3


@dataclass
class SearchMatch:
    fact: Fact
    score: float
    reason: str


@dataclass
class SearchResponse:
    matches: List[SearchMatch]


class EmbeddingBackend:
    """Wrapper around SentenceTransformer with lazy loading."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: Optional[str] = None,
        fallback_dim: int = 128,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._model: Optional[SentenceTransformer] = None
        self._fallback_dim = fallback_dim

    def ensure_model(self) -> SentenceTransformer:
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers is required for semantic search")
        if self._model is None:
            kwargs = {"device": self._device} if self._device else {}
            self._model = SentenceTransformer(self._model_name, **kwargs)
        return self._model

    def encode(self, text: str) -> tuple[float, ...]:
        if SentenceTransformer is None:
            return self._fallback_embedding(text)
        try:
            model = self.ensure_model()
            vector = model.encode(text, normalize_embeddings=True)
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            return normalize_vector(vector)
        except Exception:  # pragma: no cover - runtime fallback
            return self._fallback_embedding(text)

    def _fallback_embedding(self, text: str) -> tuple[float, ...]:
        return deterministic_embedding(text, self._fallback_dim)


class CombinedSearchService:
    """Combines fuzzy and semantic similarity to score facts."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        embedding_backend: Optional[EmbeddingBackend] = None,
    ) -> None:
        self._kb = knowledge_base
        self._embedding_backend = embedding_backend or EmbeddingBackend()

    def search(self, request: SearchRequest) -> SearchResponse:
        query = request.query.strip()
        if not query:
            return SearchResponse(matches=[])

        fuzzy_scores = self._run_fuzzy(query, request)
        semantic_scores = self._run_semantic(query, request)
        combined = self._merge_scores(
            fuzzy_scores,
            semantic_scores,
            request.fuzzy_weight,
            request.semantic_weight,
            request.top_k,
        )
        matches = [SearchMatch(fact=fact, score=score, reason=reason) for fact, score, reason in combined]
        return SearchResponse(matches=matches)

    def _run_fuzzy(self, query: str, request: SearchRequest) -> dict[str, float]:
        facts = self._kb.facts()
        if not facts:
            return {}
        choices = {fact.id: fact.text_blob() for fact in facts}
        if not choices:
            return {}
        if fuzz is None or process is None:
            return _fallback_fuzzy_search(query, choices, request.fuzzy_threshold)
        results = process.extract(  # type: ignore[arg-type]
            query,
            choices,
            scorer=fuzz.token_set_ratio,
            score_cutoff=request.fuzzy_threshold,
            limit=len(choices),
        )
        return {match_id: float(score) / 100.0 for match_id, score, _ in results}

    def _run_semantic(self, query: str, request: SearchRequest) -> dict[str, float]:
        facts = self._kb.facts()
        if not facts:
            return {}
        query_vector = self._embedding_backend.encode(query)
        fact_embeddings = self._kb.embeddings()
        if not fact_embeddings:
            return {}
        query_vector = normalize_vector(query_vector)
        fact_matrix = [normalize_vector(vec) for vec in fact_embeddings]
        scores = matrix_dot_vector(fact_matrix, query_vector)
        order = argsort_desc(scores)
        return {facts[idx].id: float(scores[idx]) for idx in order}

    def _merge_scores(
        self,
        fuzzy_scores: dict[str, float],
        semantic_scores: dict[str, float],
        fuzzy_weight: float,
        semantic_weight: float,
        top_k: int,
    ) -> List[tuple[Fact, float, str]]:
        weighted: dict[str, float] = {}
        reasons: dict[str, List[str]] = {}
        for fact_id, score in semantic_scores.items():
            weighted[fact_id] = weighted.get(fact_id, 0.0) + score * semantic_weight
            reasons.setdefault(fact_id, []).append(f"semantic={score:.2f}")
        for fact_id, score in fuzzy_scores.items():
            weighted[fact_id] = weighted.get(fact_id, 0.0) + score * fuzzy_weight
            reasons.setdefault(fact_id, []).append(f"fuzzy={score:.2f}")
        ordered = sorted(weighted.items(), key=lambda item: item[1], reverse=True)
        results: List[tuple[Fact, float, str]] = []
        for fact_id, score in ordered[:top_k]:
            fact = self._kb.get_fact(fact_id)
            if fact is None:
                continue
            reason = ", ".join(reasons.get(fact_id, []))
            results.append((fact, score, reason))
        return results


def _fallback_fuzzy_search(query: str, choices: dict[str, str], cutoff: int) -> dict[str, float]:
    import difflib

    results: dict[str, float] = {}
    for key, text in choices.items():
        ratio = difflib.SequenceMatcher(None, query.casefold(), text.casefold()).ratio()
        score = ratio * 100.0
        if score >= cutoff:
            results[key] = ratio
    return results
