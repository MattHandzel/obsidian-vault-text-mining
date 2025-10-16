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

from .service import PersonalContextService, PersonalContextResponse
from .search import SearchRequest


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
    ) -> None:
        self._console = Console()
        self._service = PersonalContextService(
            profile_path=profile_path,
            rules_path=rules_path,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
        )
        self._mcp = FastMCP(name=server_name)
        self._register_tools()

    def _register_tools(self) -> None:
        """Register FastMCP tools backed by the context service."""

        @self._mcp.tool
        def search_facts(
            query: str,
            top_k: int = 10,
            fuzzy_threshold: int = 80,
            semantic_weight: float = 1.0,
            fuzzy_weight: float = 0.3,
            domain: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Search knowledge base using semantic + fuzzy similarity with filtering."""

            request = SearchRequest(
                query=str(query),
                top_k=int(top_k),
                fuzzy_threshold=int(fuzzy_threshold),
                semantic_weight=float(semantic_weight),
                fuzzy_weight=float(fuzzy_weight),
            )
            response = self._service.query(request, domain=domain, tags=tags or [])
            return _response_to_dict(response)

        @self._mcp.tool
        def list_rules() -> Dict[str, Any]:
            """Return configured sharing rules and metadata."""

            return {
                "rules": [rule.to_dict() for rule in self._service.rule_engine.rules()],
            }

        @self._mcp.tool
        def preview_query(
            query: str,
            top_k: int = 10,
            domain: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Preview which facts would be shared without returning content."""

            request = SearchRequest(query=str(query), top_k=int(top_k))
            response = self._service.query(request, domain=domain, tags=tags or [])
            return {
                "shareable_ids": [fact.fact_id for fact in response.shared],
                "filtered_ids": response.filtered,
                "audit": {
                    "blocked_by_rules": response.audit.blocked_by_rules,
                    "blocked_by_sensitive": response.audit.blocked_by_sensitive,
                },
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
                raise ValueError("host and port are required for HTTP or SSE transports")
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
        self._mcp.run(transport=transport, **run_kwargs)


def _response_to_dict(response: PersonalContextResponse) -> Dict[str, Any]:
    """Serialize a response returned by the context service."""

    return {
        "shared": [
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
        ],
        "filtered": response.filtered,
        "audit": {
            "allowed": response.audit.allowed,
            "blocked_by_rules": response.audit.blocked_by_rules,
            "blocked_by_sensitive": response.audit.blocked_by_sensitive,
        },
    }

