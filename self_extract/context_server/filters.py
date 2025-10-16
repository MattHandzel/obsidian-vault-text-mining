"""Sensitive data filtering utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import re

from .data import Fact
from .search import EmbeddingBackend
from .math_utils import dot, normalize_vector


@dataclass
class FilterDecision:
    allowed: List[Fact]
    blocked: List[Fact]
    reasons: Dict[str, List[str]] = field(default_factory=dict)


class SensitiveFilter:
    """Blocks facts that match sensitive heuristics."""

    DEFAULT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
        "medical": (
            "diagnosis",
            "illness",
            "symptom",
            "therapy",
            "medication",
            "health condition",
        ),
        "sexual": (
            "sexual",
            "sex",
            "sex life",
            "sexual preference",
            "intimate",
            "intimacy",
            "fetish",
        ),
        "opinion": (
            "thinks",
            "believes",
            "opinion",
            "complain",
            "judgment",
        ),
        "private": (
            "password",
            "secret",
            "embarrassing",
            "insecure",
            "confidential",
        ),
    }

    DEFAULT_PATTERNS: Dict[str, Tuple[re.Pattern[str], ...]] = {
        "medical": (
            re.compile(r"\b(blood pressure|diagnosed|therapy)\b", re.IGNORECASE),
        ),
        "sexual": (
            re.compile(r"\b(sexual|intimate)\b", re.IGNORECASE),
        ),
        "opinion": (
            re.compile(r"\b(thinks|feels|believes)\b", re.IGNORECASE),
        ),
        "private": (
            re.compile(r"\b(secret|password|private)\b", re.IGNORECASE),
        ),
    }

    DEFAULT_SEMANTIC_LABELS: Dict[str, Tuple[str, ...]] = {
        "medical": ("medical history", "doctor visit", "symptom"),
        "sexual": ("romantic life", "sexual preference", "intimate detail"),
        "opinion": ("personal opinion", "judgment about others"),
        "private": ("private detail", "confidential information"),
    }

    def __init__(
        self,
        embedding_backend: EmbeddingBackend,
        keyword_overrides: Optional[Dict[str, Tuple[str, ...]]] = None,
        semantic_threshold: float = 0.82,
    ) -> None:
        self._backend = embedding_backend
        self._keywords = keyword_overrides or self.DEFAULT_KEYWORDS
        self._semantic_threshold = semantic_threshold
        self._label_vectors: Dict[str, List[Tuple[float, ...]]] = {}
        self._keyword_patterns: Dict[str, List[Tuple[str, re.Pattern[str]]]] = {}
        self._prepare_keyword_patterns()
        self._prepare_semantic_vectors()

    def _prepare_keyword_patterns(self) -> None:
        patterns: Dict[str, List[Tuple[str, re.Pattern[str]]]] = {}
        for label, keywords in self._keywords.items():
            label_patterns: List[Tuple[str, re.Pattern[str]]] = []
            for keyword in keywords:
                token = keyword.strip()
                if not token:
                    continue
                regex = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
                label_patterns.append((token, regex))
            if label_patterns:
                patterns[label] = label_patterns
        self._keyword_patterns = patterns

    def _prepare_semantic_vectors(self) -> None:
        for label, prompts in self.DEFAULT_SEMANTIC_LABELS.items():
            vectors = [self._backend.encode(prompt) for prompt in prompts]
            norms = [normalize_vector(vec) for vec in vectors if vec]
            if norms:
                self._label_vectors[label] = norms

    def evaluate(self, facts: Iterable[Fact]) -> FilterDecision:
        allowed: List[Fact] = []
        blocked: List[Fact] = []
        reasons: Dict[str, List[str]] = {}
        for fact in facts:
            reason_list: List[str] = []
            if self._has_explicit_sensitivity(fact, reason_list):
                blocked.append(fact)
                reasons[fact.id] = reason_list
                continue
            if self._matches_keywords(fact, reason_list) or self._matches_patterns(fact, reason_list):
                blocked.append(fact)
                reasons[fact.id] = reason_list
                continue
            if self._matches_semantic(fact, reason_list):
                blocked.append(fact)
                reasons[fact.id] = reason_list
                continue
            allowed.append(fact)
        return FilterDecision(allowed=allowed, blocked=blocked, reasons=reasons)

    def _has_explicit_sensitivity(self, fact: Fact, reasons: List[str]) -> bool:
        level = (fact.sensitivity_level or "").lower()
        if level in {"personal", "sensitive"}:
            reasons.append(f"sensitivity:{level}")
            return True
        if any(reason.lower() in {"personal", "sensitive", "private"} for reason in fact.sensitivity_reasons):
            reasons.append("sensitivity:reason_tag")
            return True
        if {"private", "medical", "embarrassing"}.intersection({tag.lower() for tag in fact.tags}):
            reasons.append("sensitivity:tag_match")
            return True
        return False

    def _matches_keywords(self, fact: Fact, reasons: List[str]) -> bool:
        text = fact.text_blob()
        for label, patterns in self._keyword_patterns.items():
            for keyword, pattern in patterns:
                if pattern.search(text):
                    reasons.append(f"keyword:{label}:{keyword}")
                    return True
        return False

    def _matches_patterns(self, fact: Fact, reasons: List[str]) -> bool:
        for label, patterns in self.DEFAULT_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(fact.text_blob()):
                    reasons.append(f"pattern:{label}:{pattern.pattern}")
                    return True
        return False

    def _matches_semantic(self, fact: Fact, reasons: List[str]) -> bool:
        fact_vec = normalize_vector(fact.embedding)
        for label, matrix in self._label_vectors.items():
            scores = [dot(row, fact_vec) for row in matrix]
            if not scores:
                continue
            max_score = max(scores)
            if max_score >= self._semantic_threshold:
                reasons.append(f"semantic:{label}:{max_score:.2f}")
                return True
        return False
