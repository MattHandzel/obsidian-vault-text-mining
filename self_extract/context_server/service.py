"""High-level orchestration for the personal context server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from .data import KnowledgeBase
from .filters import FilterDecision, SensitiveFilter
from .rules import QueryContext, RuleDecision, RuleEngine
from .search import CombinedSearchService, EmbeddingBackend, SearchRequest, SearchResponse


@dataclass
class SharedFact:
    fact_id: str
    title: str
    summary: str
    domain: str
    tags: List[str]
    score: float
    search_reason: str
    rule_action: Optional[str]
    rule_reason: Optional[str]


@dataclass
class QueryAudit:
    allowed: List[str]
    blocked_by_rules: Dict[str, str]
    blocked_by_sensitive: Dict[str, List[str]]


@dataclass
class PersonalContextResponse:
    shared: List[SharedFact]
    filtered: List[str]
    audit: QueryAudit


class PersonalContextService:
    """Coordinates knowledge base, search, rules, and sensitive filtering."""

    def __init__(
        self,
        profile_path: Path,
        rules_path: Path,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_device: Optional[str] = None,
    ) -> None:
        self._embedding_backend = EmbeddingBackend(model_name=embedding_model, device=embedding_device)
        self._knowledge_base = KnowledgeBase(profile_path)
        self._rules = RuleEngine(rules_path, self._embedding_backend)
        self._sensitive = SensitiveFilter(self._embedding_backend)
        self._search = CombinedSearchService(self._knowledge_base, self._embedding_backend)

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._knowledge_base

    @property
    def rule_engine(self) -> RuleEngine:
        return self._rules

    @property
    def sensitive_filter(self) -> SensitiveFilter:
        return self._sensitive

    @property
    def search_service(self) -> CombinedSearchService:
        return self._search

    def reload(self) -> None:
        self._knowledge_base.reload()
        self._rules.reload()

    def query(
        self,
        request: SearchRequest,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> PersonalContextResponse:
        search_response = self._search.search(request)
        context = QueryContext(
            query=request.query,
            domain=domain,
            tags=tuple(tags or []),
        )
        rule_decision = self._rules.apply([match.fact for match in search_response.matches], context)
        sensitive_decision = self._sensitive.evaluate(rule_decision.allowed)
        shared = self._build_shared_facts(search_response, rule_decision, sensitive_decision)
        filtered_ids: Set[str] = {fact.id for fact in rule_decision.blocked}
        filtered_ids.update(fact.id for fact in sensitive_decision.blocked)
        audit = QueryAudit(
            allowed=[item.fact_id for item in shared],
            blocked_by_rules={
                fact.id: rule_decision.matches[fact.id].reason
                for fact in rule_decision.blocked
                if fact.id in rule_decision.matches
            },
            blocked_by_sensitive=sensitive_decision.reasons,
        )
        return PersonalContextResponse(shared=shared, filtered=sorted(filtered_ids), audit=audit)

    def _build_shared_facts(
        self,
        search_response: SearchResponse,
        rule_decision: RuleDecision,
        sensitive_decision: FilterDecision,
    ) -> List[SharedFact]:
        sensitive_blocked = {fact.id for fact in sensitive_decision.blocked}
        allowed_ids = {fact.id for fact in rule_decision.allowed}
        shared: List[SharedFact] = []
        for match in search_response.matches:
            fact = match.fact
            if fact.id not in allowed_ids or fact.id in sensitive_blocked:
                continue
            rule_match = rule_decision.matches.get(fact.id)
            shared.append(
                SharedFact(
                    fact_id=fact.id,
                    title=fact.title,
                    summary=fact.summary,
                    domain=fact.domain,
                    tags=list(fact.tags),
                    score=match.score,
                    search_reason=match.reason,
                    rule_action=rule_match.action.value if rule_match else None,
                    rule_reason=rule_match.reason if rule_match else None,
                )
            )
        return shared
