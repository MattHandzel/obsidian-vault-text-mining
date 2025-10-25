"""FastMCP-powered server exposing the personal context service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
except ImportError:  # pragma: no cover - optional dependency

    class Console:  # type: ignore[no-redef]
        def print(self, *args: Any, **_kwargs: Any) -> None:
            __import__("builtins").print(*args)


from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from mcp.server.auth.middleware.auth_context import get_access_token

from .service import PersonalContextService, PersonalContextResponse
from .search import SearchRequest

ALLOWED_EMAIL = "handzelmatthew@gmail.com"


class ContextMCPServer:
    """Expose context tools via the FastMCP framework."""

    def __init__(
        self,
        profile_path: Path,
        rules_path: Path,
        *,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_device: Optional[str] = None,
        server_name: str = "Personal Context Server",
        auth: Optional[AuthProvider] = None,
    ) -> None:
        self._console = Console()
        self._service = PersonalContextService(
            profile_path=profile_path,
            rules_path=rules_path,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
        )
        self._auth = auth
        self._mcp = FastMCP(name=server_name, auth=auth)
        self._register_tools()

    @staticmethod
    def _extract_email() -> Optional[str]:
        """Return the authenticated user's email claim, if available."""

        token = get_access_token()
        if token is None:
            return None
        claims = getattr(token, "claims", {}) or {}
        for key in ("email", "preferred_username", "upn"):
            value = claims.get(key)
            if isinstance(value, str) and value:
                return value.casefold()
        return None

    def _require_authorized_user(self) -> None:
        """Ensure the active request belongs to the approved account."""

        email = self._extract_email()
        if email != ALLOWED_EMAIL:
            raise PermissionError(
                "Access denied: this MCP server is restricted to handzelmatthew@gmail.com."
            )

    def _register_tools(self) -> None:
        """Register FastMCP tools backed by the context service."""

        @self._mcp.tool(annotations={"readOnlyHint": True})
        def search_facts(
            query: str,
            top_k: int = 10,
            fuzzy_threshold: int = 80,
            semantic_weight: float = 1.0,
            fuzzy_weight: float = 0.3,
            domain: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Retrieve shareable facts ranked by semantic + fuzzy relevance.

            Args:
                query: Natural language search string evaluated against fact titles,
                    summaries, tags, and evidence.
                top_k: Maximum number of ranked results to include (after filtering).
                fuzzy_threshold: Minimum RapidFuzz token-set score (0–100) for textual
                    matches before weighting.
                semantic_weight: Weight applied to embedding cosine similarity.
                fuzzy_weight: Weight applied to lexical similarity scores.
                domain: Optional domain name used to constrain matches (e.g., ``facts``).
                tags: Optional list of tags; all provided tags must appear on a fact.

            Returns:
                Mapping with the original request parameters, ranked fact metadata,
                filtered identifiers, audit breakdown, numeric summary, and a textual
                explanation geared toward LLM agents.

            Raises:
                PermissionError: Caller is not authorized to use the context tools.
                RuntimeError: Embedding model cannot be loaded or encode the query.
            """

            self._require_authorized_user()

            tag_list = list(tags or [])
            request = SearchRequest(
                query=str(query),
                top_k=int(top_k),
                fuzzy_threshold=int(fuzzy_threshold),
                semantic_weight=float(semantic_weight),
                fuzzy_weight=float(fuzzy_weight),
            )
            response = self._service.query(request, domain=domain, tags=tag_list)
            return _response_to_dict(
                response=response,
                query=str(query),
                top_k=int(top_k),
                domain=domain,
                tags=tag_list,
                fuzzy_threshold=int(fuzzy_threshold),
                semantic_weight=float(semantic_weight),
                fuzzy_weight=float(fuzzy_weight),
            )

        @self._mcp.tool(annotations={"readOnlyHint": True})
        def list_rules() -> Dict[str, Any]:
            """Describe active sharing rules evaluated during searches.

            Returns:
                A mapping with serialized rule definitions and a summary count so
                LLMs can reason about potential policy blocks.

            Raises:
                PermissionError: Caller is not authorized to use the context tools.
            """

            self._require_authorized_user()

            rules = [rule.to_dict() for rule in self._service.rule_engine.rules()]
            return {
                "rules": rules,
                "summary": {
                    "rule_count": len(rules),
                },
            }

        @self._mcp.tool(annotations={"readOnlyHint": True})
        def preview_query(
            query: str,
            top_k: int = 10,
            domain: Optional[str] = None,
            tags: Optional[List[str]] = None,
            fuzzy_threshold: int = 80,
            semantic_weight: float = 1.0,
            fuzzy_weight: float = 0.3,
        ) -> Dict[str, Any]:
            """Preview which facts would be shared without returning content.

            Args mirror :func:`search_facts`. The response only includes identifiers,
            audit data, and an explanation string so an orchestrating LLM can decide
            whether to proceed with a full retrieval.

            Raises:
                PermissionError: Caller is not authorized to use the context tools.
                RuntimeError: Embedding model cannot be loaded or encode the query.
            """

            self._require_authorized_user()

            tag_list = list(tags or [])
            request = SearchRequest(
                query=str(query),
                top_k=int(top_k),
                fuzzy_threshold=int(fuzzy_threshold),
                semantic_weight=float(semantic_weight),
                fuzzy_weight=float(fuzzy_weight),
            )
            response = self._service.query(request, domain=domain, tags=tag_list)
            shareable_ids = [fact.fact_id for fact in response.shared]
            filtered_ids = response.filtered
            audit = {
                "blocked_by_rules": response.audit.blocked_by_rules,
                "blocked_by_sensitive": response.audit.blocked_by_sensitive,
            }
            explanation = _build_explanation(
                query=str(query),
                top_k=int(top_k),
                domain=domain,
                tags=tag_list,
                shared_count=len(shareable_ids),
                filtered_count=len(filtered_ids),
                blocked_rules=len(audit["blocked_by_rules"]),
                blocked_sensitive=len(audit["blocked_by_sensitive"]),
            )
            return {
                "request": {
                    "query": str(query),
                    "top_k": int(top_k),
                    "domain": domain,
                    "tags": tag_list,
                    "fuzzy_threshold": int(fuzzy_threshold),
                    "semantic_weight": float(semantic_weight),
                    "fuzzy_weight": float(fuzzy_weight),
                },
                "shareable_ids": shareable_ids,
                "filtered_ids": filtered_ids,
                "audit": audit,
                "explanation": explanation,
            }

    def run(
        self,
        *,
        transport: str = "http",
        host: Optional[str] = None,
        port: Optional[int] = None,
        path: Optional[str] = "/mcp",
    ) -> None:
        """Run the FastMCP server using the requested transport."""

        run_kwargs: Dict[str, Any] = {}
        if transport in {"http", "sse"}:
            if host is None or port is None:
                raise ValueError(
                    "host and port are required for HTTP or SSE transports"
                )
            run_kwargs["host"] = host
            run_kwargs["port"] = port
        if transport == "http" and path is not None:
            run_kwargs["path"] = path

        location = []
        if transport in {"http", "sse"}:
            location.append(f"{transport}://{host}:{port}")
        else:
            location.append(transport)
        self._console.print(
            f"[green]Context MCP server running via FastMCP on[/green] {' '.join(location)}"
        )
        if self._auth is not None:
            provider_name = type(self._auth).__name__
            self._console.print(f"[cyan]{provider_name} authentication enabled[/cyan]")
        self._mcp.run(transport=transport, **run_kwargs)


def _response_to_dict(
    *,
    response: PersonalContextResponse,
    query: str,
    top_k: int,
    domain: Optional[str],
    tags: List[str],
    fuzzy_threshold: int,
    semantic_weight: float,
    fuzzy_weight: float,
) -> Dict[str, Any]:
    """Serialize a context response with rich metadata for LLM agents.

    The structure mirrors the CLI output but adds request echoing, a numeric summary,
    and a narrative explanation so clients can reason about downstream actions.
    """

    shared_payload = [
        {
            "id": fact.fact_id,
            "title": fact.title,
            "summary": fact.summary,
            "domain": fact.domain,
            "tags": fact.tags,
            "score": fact.score,
            "search_reason": fact.search_reason,
            "rule_action": fact.rule_action,
            "rule_reason": fact.rule_reason,
        }
        for fact in response.shared
    ]
    filtered = response.filtered
    audit = {
        "allowed": response.audit.allowed,
        "blocked_by_rules": response.audit.blocked_by_rules,
        "blocked_by_sensitive": response.audit.blocked_by_sensitive,
    }
    explanation = _build_explanation(
        query=query,
        top_k=top_k,
        domain=domain,
        tags=tags,
        shared_count=len(shared_payload),
        filtered_count=len(filtered),
        blocked_rules=len(audit["blocked_by_rules"]),
        blocked_sensitive=len(audit["blocked_by_sensitive"]),
    )
    return {
        "request": {
            "query": query,
            "top_k": top_k,
            "domain": domain,
            "tags": tags,
            "fuzzy_threshold": fuzzy_threshold,
            "semantic_weight": semantic_weight,
            "fuzzy_weight": fuzzy_weight,
        },
        "shared": shared_payload,
        "filtered": filtered,
        "audit": audit,
        "summary": {
            "shared_count": len(shared_payload),
            "filtered_count": len(filtered),
            "blocked_by_rules": len(audit["blocked_by_rules"]),
            "blocked_by_sensitive": len(audit["blocked_by_sensitive"]),
        },
        "explanation": explanation,
    }


def _build_explanation(
    *,
    query: str,
    top_k: int,
    domain: Optional[str],
    tags: List[str],
    shared_count: int,
    filtered_count: int,
    blocked_rules: int,
    blocked_sensitive: int,
) -> str:
    """Generate a human-readable summary for LLM consumption."""

    scope_parts: List[str] = [f"query='{query}'", f"top_k={top_k}"]
    if domain:
        scope_parts.append(f"domain='{domain}'")
    if tags:
        scope_parts.append(f"tags={tags}")
    scope_text = ", ".join(scope_parts)
    details = [
        f"Shared {shared_count} fact(s) and filtered {filtered_count} fact(s).",
        f"Blocked by rules: {blocked_rules}; blocked by sensitive filter: {blocked_sensitive}.",
    ]
    return f"Search executed with {scope_text}. " + " ".join(details)
