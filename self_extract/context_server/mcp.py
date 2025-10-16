"""Minimal Model Context Protocol server exposing the context service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from rich.console import Console
except ImportError:  # pragma: no cover - optional dependency
    class Console:  # type: ignore[no-redef]
        def print(self, *args: Any, **_kwargs: Any) -> None:
            __import__("builtins").print(*args)

from .service import PersonalContextService, PersonalContextResponse, SharedFact
from .search import SearchRequest


class ContextMCPServer:
    """Simple JSON-RPC server compatible with basic MCP tooling."""

    def __init__(
        self,
        profile_path: Path,
        rules_path: Path,
        host: str = "127.0.0.1",
        port: int = 8077,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_device: Optional[str] = None,
    ) -> None:
        self._service = PersonalContextService(
            profile_path=profile_path,
            rules_path=rules_path,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
        )
        self._host = host
        self._port = port
        self._console = Console()

    async def start(self) -> None:
        try:
            server = await asyncio.start_server(self._handle_client, self._host, self._port)
        except OSError as exc:  # pragma: no cover - sandbox fallback
            self._console.print(f"[red]Failed to bind MCP server:[/red] {exc}")
            return
        addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        self._console.print(f"[green]Context MCP server listening on[/green] {addr}")
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self._console.print(f"[cyan]Client connected:[/cyan] {peer}")
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    await self._send_error(writer, None, code=-32700, message="Parse error")
                    continue
                response = await self._dispatch(request)
                await self._send(writer, response)
        finally:
            writer.close()
            await writer.wait_closed()
            self._console.print(f"[cyan]Client disconnected:[/cyan] {peer}")

    async def _dispatch(self, request: Dict[str, Any]) -> Dict[str, Any]:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        try:
            if method == "tools/list":
                result = self._list_tools()
            elif method == "tools/call":
                result = await self._call_tool(params)
            elif method == "ping":
                result = {"pong": True}
            else:
                return self._error(request_id, -32601, f"Unknown method: {method}")
        except Exception as exc:  # pragma: no cover - defensive logging
            self._console.print(f"[red]Error handling request[/red] {request}: {exc}")
            return self._error(request_id, -32603, str(exc))
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    async def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "search_facts":
            return self._tool_search(arguments)
        if name == "list_rules":
            return self._tool_list_rules()
        if name == "preview_query":
            return self._tool_preview(arguments)
        raise ValueError(f"Unknown tool {name}")

    def _tool_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        request = SearchRequest(
            query=str(arguments.get("query", "")),
            top_k=int(arguments.get("top_k", 10)),
            fuzzy_threshold=int(arguments.get("fuzzy_threshold", 80)),
            semantic_weight=float(arguments.get("semantic_weight", 1.0)),
            fuzzy_weight=float(arguments.get("fuzzy_weight", 0.3)),
        )
        domain = arguments.get("domain")
        tags = arguments.get("tags") or []
        response = self._service.query(request, domain=domain, tags=tags)
        return _response_to_dict(response)

    def _tool_list_rules(self) -> Dict[str, Any]:
        return {
            "rules": [rule.to_dict() for rule in self._service.rule_engine.rules()],
        }

    def _tool_preview(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        request = SearchRequest(
            query=str(arguments.get("query", "")),
            top_k=int(arguments.get("top_k", 10)),
        )
        domain = arguments.get("domain")
        tags = arguments.get("tags") or []
        response = self._service.query(request, domain=domain, tags=tags)
        return {
            "shareable_ids": [fact.fact_id for fact in response.shared],
            "filtered_ids": response.filtered,
            "audit": {
                "blocked_by_rules": response.audit.blocked_by_rules,
                "blocked_by_sensitive": response.audit.blocked_by_sensitive,
            },
        }

    def _list_tools(self) -> Dict[str, Any]:
        return {
            "tools": [
                {
                    "name": "search_facts",
                    "description": "Search knowledge base using fuzzy + semantic similarity with filtering",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "minimum": 1, "default": 10},
                            "fuzzy_threshold": {"type": "integer", "minimum": 0, "maximum": 100, "default": 80},
                            "semantic_weight": {"type": "number", "default": 1.0},
                            "fuzzy_weight": {"type": "number", "default": 0.3},
                            "domain": {"type": ["string", "null"]},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                            },
                        },
                        "required": ["query"],
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "shared": {"type": "array"},
                            "filtered": {"type": "array"},
                            "audit": {"type": "object"},
                        },
                    },
                },
                {
                    "name": "list_rules",
                    "description": "Return configured sharing rules including metadata.",
                    "input_schema": {"type": "object"},
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "rules": {"type": "array"},
                        },
                    },
                },
                {
                    "name": "preview_query",
                    "description": "Preview which facts would be shared for a query, without returning data.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "minimum": 1, "default": 10},
                            "domain": {"type": ["string", "null"]},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                            },
                        },
                        "required": ["query"],
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "shareable_ids": {"type": "array"},
                            "filtered_ids": {"type": "array"},
                            "audit": {"type": "object"},
                        },
                    },
                },
            ]
        }

    async def _send(self, writer: asyncio.StreamWriter, response: Dict[str, Any]) -> None:
        blob = json.dumps(response)
        writer.write(blob.encode("utf-8") + b"\n")
        await writer.drain()

    async def _send_error(
        self,
        writer: asyncio.StreamWriter,
        request_id: Optional[str],
        code: int,
        message: str,
    ) -> None:
        payload = self._error(request_id, code, message)
        await self._send(writer, payload)

    def _error(self, request_id: Optional[str], code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def _response_to_dict(response: PersonalContextResponse) -> Dict[str, Any]:
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
