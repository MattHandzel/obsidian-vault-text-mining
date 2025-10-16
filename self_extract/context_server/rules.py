"""Rule engine handling pattern and semantic filters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import json
import re
from uuid import uuid4

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional dependency
    fuzz = None

from .data import Fact
from .search import EmbeddingBackend
from .math_utils import dot, normalize_vector


def _fuzzy_score(pattern: str, text: str) -> float:
    if fuzz is not None:
        return float(fuzz.token_set_ratio(pattern, text)) / 100.0
    from difflib import SequenceMatcher

    return SequenceMatcher(None, pattern.casefold(), text.casefold()).ratio()


class RuleAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class RuleKind(str, Enum):
    PATTERN = "pattern"
    SEMANTIC = "semantic"


@dataclass
class QueryContext:
    """Additional query metadata used when evaluating rules."""

    query: str
    domain: Optional[str] = None
    tags: Tuple[str, ...] = tuple()
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class Rule:
    id: str
    action: RuleAction
    kind: RuleKind
    description: str = ""
    pattern_type: str = "regex"  # regex or fuzzy
    patterns: Tuple[str, ...] = field(default_factory=tuple)
    labels: Tuple[str, ...] = field(default_factory=tuple)
    domains: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    threshold: float = 0.85
    metadata: Dict[str, object] = field(default_factory=dict)
    _compiled_regex: Tuple[re.Pattern[str], ...] = field(default_factory=tuple, init=False, repr=False)
    _label_vectors: Optional[List[Tuple[float, ...]]] = field(default=None, init=False, repr=False)

    @staticmethod
    def new(
        action: RuleAction,
        kind: RuleKind,
        description: str = "",
        **kwargs: object,
    ) -> "Rule":
        rule_id = kwargs.get("id") or str(uuid4())
        rule = Rule(
            id=str(rule_id),
            action=action,
            kind=kind,
            description=description,
            pattern_type=str(kwargs.get("pattern_type", "regex")),
            patterns=tuple(str(item) for item in kwargs.get("patterns", []) or []),
            labels=tuple(str(item) for item in kwargs.get("labels", []) or []),
            domains=tuple(str(item) for item in kwargs.get("domains", []) or []),
            tags=tuple(str(item) for item in kwargs.get("tags", []) or []),
            threshold=float(kwargs.get("threshold", 0.85)),
            metadata=kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {},
        )
        rule._prepare_regex()
        return rule

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "action": self.action.value,
            "kind": self.kind.value,
            "description": self.description,
            "pattern_type": self.pattern_type,
            "patterns": list(self.patterns),
            "labels": list(self.labels),
            "domains": list(self.domains),
            "tags": list(self.tags),
            "threshold": self.threshold,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "Rule":
        action = RuleAction(str(payload["action"]))
        kind = RuleKind(str(payload["kind"]))
        pattern_type = str(payload.get("pattern_type", "regex"))
        patterns = tuple(str(item) for item in payload.get("patterns", []) if str(item))
        labels = tuple(str(item) for item in payload.get("labels", []) if str(item))
        domains = tuple(str(item) for item in payload.get("domains", []) if str(item))
        tags = tuple(str(item) for item in payload.get("tags", []) if str(item))
        threshold = float(payload.get("threshold", 0.85))
        description = str(payload.get("description", ""))
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        rule = Rule(
            id=str(payload.get("id") or uuid4()),
            action=action,
            kind=kind,
            description=description,
            pattern_type=pattern_type,
            patterns=patterns,
            labels=labels,
            domains=domains,
            tags=tags,
            threshold=threshold,
            metadata=metadata,
        )
        rule._prepare_regex()
        return rule

    def _prepare_regex(self) -> None:
        if self.kind is not RuleKind.PATTERN or self.pattern_type != "regex":
            self._compiled_regex = tuple()
            return
        compiled: List[re.Pattern[str]] = []
        for pattern in self.patterns:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern `{pattern}`: {exc}") from exc
        self._compiled_regex = tuple(compiled)

    def ensure_embeddings(self, backend: EmbeddingBackend) -> None:
        if self.kind is not RuleKind.SEMANTIC:
            return
        if self._label_vectors is None:
            vectors = [normalize_vector(backend.encode(label)) for label in self.labels]
            self._label_vectors = vectors if vectors else []

    def applies_to_fact(
        self,
        fact: Fact,
        backend: EmbeddingBackend,
        context: Optional[QueryContext] = None,
    ) -> Optional[str]:
        if self.domains:
            if fact.domain not in self.domains and (
                context is None or context.domain not in self.domains
            ):
                return None
        if self.tags:
            fact_tags = set(tag.lower() for tag in fact.tags)
            if not fact_tags.intersection(tag.lower() for tag in self.tags):
                context_tags = set(tag.lower() for tag in (context.tags if context else ()))
                if not context_tags.intersection(tag.lower() for tag in self.tags):
                    return None
        if self.kind is RuleKind.PATTERN:
            return self._match_pattern(fact, context)
        if self.kind is RuleKind.SEMANTIC:
            return self._match_semantic(fact, backend, context)
        return None

    def _match_pattern(self, fact: Fact, context: Optional[QueryContext]) -> Optional[str]:
        text = fact.text_blob()
        if context:
            text = f"{text}\n{context.query}"
        if self.pattern_type == "regex":
            for regex in self._compiled_regex:
                if regex.search(text):
                    return f"regex:{regex.pattern}"
            return None
        for pattern in self.patterns:
            score = _fuzzy_score(pattern, text)
            if score >= self.threshold:
                return f"fuzzy:{pattern}:{score:.2f}"
        return None

    def _match_semantic(
        self,
        fact: Fact,
        backend: EmbeddingBackend,
        context: Optional[QueryContext],
    ) -> Optional[str]:
        self.ensure_embeddings(backend)
        if not self._label_vectors:
            return None
        fact_vec = normalize_vector(fact.embedding)
        label_matrix = self._label_vectors
        sims = [dot(label_vec, fact_vec) for label_vec in label_matrix]
        if not sims:
            return None
        best_idx = max(range(len(sims)), key=lambda idx: sims[idx])
        best_score = sims[best_idx]
        if context and context.query:
            query_vec = normalize_vector(backend.encode(context.query))
            query_scores = [dot(label_vec, query_vec) for label_vec in label_matrix]
            if query_scores:
                context_best_idx = max(range(len(query_scores)), key=lambda idx: query_scores[idx])
                context_best_score = query_scores[context_best_idx]
                if context_best_score > best_score:
                    best_score = context_best_score
                    best_idx = context_best_idx
        if best_score >= self.threshold:
            label = self.labels[best_idx] if best_idx < len(self.labels) else "label"
            return f"semantic:{label}:{best_score:.2f}"
        return None


@dataclass
class RuleMatch:
    rule_id: str
    action: RuleAction
    reason: str
    description: str


@dataclass
class RuleDecision:
    allowed: List[Fact]
    blocked: List[Fact]
    matches: Dict[str, RuleMatch]


class RuleEngine:
    """Evaluates rules in order against facts."""

    def __init__(
        self,
        rules_path: Path,
        embedding_backend: EmbeddingBackend,
    ) -> None:
        self._path = rules_path
        self._backend = embedding_backend
        self._rules: List[Rule] = []
        self.reload()

    @property
    def path(self) -> Path:
        return self._path

    def rules(self) -> List[Rule]:
        return list(self._rules)

    def reload(self) -> None:
        if not self._path.exists():
            self._rules = []
            return
        data = json.loads(self._path.read_text(encoding="utf-8"))
        payload = data.get("rules", []) if isinstance(data, dict) else data
        rules: List[Rule] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            rule = Rule.from_dict(entry)
            rules.append(rule)
        self._rules = rules

    def save(self) -> None:
        payload = {"rules": [rule.to_dict() for rule in self._rules]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert_rule(self, rule: Rule) -> None:
        rule._prepare_regex()
        existing = {r.id: idx for idx, r in enumerate(self._rules)}
        if rule.id in existing:
            self._rules[existing[rule.id]] = rule
        else:
            self._rules.append(rule)
        self.save()

    def delete_rule(self, rule_id: str) -> bool:
        for idx, rule in enumerate(self._rules):
            if rule.id == rule_id:
                del self._rules[idx]
                self.save()
                return True
        return False

    def apply(
        self,
        facts: Sequence[Fact],
        context: Optional[QueryContext] = None,
    ) -> RuleDecision:
        allowed: List[Fact] = []
        blocked: List[Fact] = []
        matches: Dict[str, RuleMatch] = {}
        for fact in facts:
            match = self._evaluate_fact(fact, context)
            if match and match.action is RuleAction.DENY:
                blocked.append(fact)
                matches[fact.id] = match
            else:
                allowed.append(fact)
                if match:
                    matches[fact.id] = match
        return RuleDecision(allowed=allowed, blocked=blocked, matches=matches)

    def _evaluate_fact(self, fact: Fact, context: Optional[QueryContext]) -> Optional[RuleMatch]:
        for rule in self._rules:
            reason = rule.applies_to_fact(fact, self._backend, context)
            if reason is None:
                continue
            return RuleMatch(
                rule_id=rule.id,
                action=rule.action,
                reason=reason,
                description=rule.description,
            )
        return None
