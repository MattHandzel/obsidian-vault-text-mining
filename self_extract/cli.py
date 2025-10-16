from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import typer
    _HAS_TYPER = True
except ImportError:  # pragma: no cover - fallback CLI
    import inspect
    import sys

    _HAS_TYPER = False

    class _DummyTyper:
        def __init__(self, help: str | None = None) -> None:
            self.help = help
            self.commands: dict[str, callable] = {}

        def command(self, name: str | None = None, *args, **kwargs):
            def decorator(func):
                cmd_name = name or func.__name__
                self.commands[cmd_name.replace("_", "-")] = func
                return func

            return decorator

        def add_typer(self, typer_obj: "_DummyTyper", name: str) -> None:
            self.commands[name] = typer_obj

        def __call__(self) -> None:
            args = sys.argv[1:]
            _dispatch(self, args)

    def _dispatch(app: _DummyTyper, argv: List[str]) -> None:
        if not argv:
            raise SystemExit("No command provided")
        sub = argv.pop(0)
        target = app.commands.get(sub)
        if target is None:
            raise SystemExit(f"Unknown command: {sub}")
        if isinstance(target, _DummyTyper):
            _dispatch(target, argv)
            return
        _invoke_command(target, argv)

    def _convert_value(param, value: str):
        target_type = param.annotation
        if target_type is inspect._empty:
            return value
        origin = getattr(target_type, "__origin__", None)
        if origin is list or origin is List:
            inner = target_type.__args__[0]
            return [inner(value)] if inner in (int, float) else [inner(value) if callable(inner) else value]
        if target_type in (str, Optional[str]):
            return value
        if target_type in (int, Optional[int]):
            return int(value)
        if target_type in (float, Optional[float]):
            return float(value)
        if target_type is bool or target_type == Optional[bool]:
            return value.lower() not in {"0", "false", "no"}
        if target_type is Path or target_type == Optional[Path]:
            return Path(value)
        return value

    def _invoke_command(func, argv: List[str]) -> None:
        signature = inspect.signature(func)
        params = list(signature.parameters.values())
        positional_iter = iter(params)
        kwargs = {}
        list_accumulators: dict[str, List] = {}
        remaining_positional_params = [
            p
            for p in params
            if (p.default is inspect._empty or p.default is Ellipsis)
            and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        args_iter = iter(argv)
        positional_consumed = 0
        for token in args_iter:
            if token.startswith("--"):
                key = token[2:].replace("-", "_")
                param = signature.parameters.get(key)
                if param is None:
                    continue
                if param.annotation in (bool, Optional[bool]):
                    kwargs[key] = True
                    continue
                try:
                    value = next(args_iter)
                except StopIteration as exc:  # pragma: no cover
                    raise SystemExit(f"Missing value for --{key}") from exc
                converted = _convert_value(param, value)
                if getattr(param.annotation, "__origin__", None) in (list, List):
                    list_accumulators.setdefault(key, [])
                    list_accumulators[key].extend(converted if isinstance(converted, list) else [converted])
                else:
                    kwargs[key] = converted
            else:
                if positional_consumed >= len(remaining_positional_params):
                    continue
                param = remaining_positional_params[positional_consumed]
                positional_consumed += 1
                kwargs[param.name] = _convert_value(param, token)
        for key, values in list_accumulators.items():
            kwargs[key] = values
        for param in params:
            if param.name not in kwargs:
                default = param.default
                if default is not inspect._empty and default is not Ellipsis:
                    kwargs[param.name] = default
        func(**kwargs)

    def Argument(default=None, *args, **kwargs):  # noqa: N802 - mimic typer API
        return default

    def Option(default=None, *args, **kwargs):  # noqa: N802 - mimic typer API
        return default

    typer = type("typer", (), {"Typer": _DummyTyper, "Argument": staticmethod(Argument), "Option": staticmethod(Option)})


try:  # pragma: no cover - optional dependency
    from rich import print
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover - fallback to stdlib
    def print(*args, **kwargs):  # type: ignore[override]
        __import__("builtins").print(*args, **kwargs)

    class _PlainConsole:
        def print(self, *args, **kwargs) -> None:  # pragma: no cover - fallback path
            __import__("builtins").print(*args, **kwargs)

    class _PlainTable:
        def __init__(self, title: str | None = None) -> None:
            self._title = title
            self._rows: List[List[str]] = []
            self._headers: List[str] = []

        def add_column(self, header: str, **_kwargs) -> None:
            self._headers.append(header)

        def add_row(self, *values: str) -> None:
            self._rows.append([str(value) for value in values])

        def __str__(self) -> str:
            lines = []
            if self._title:
                lines.append(self._title)
            if self._headers:
                lines.append(" | ".join(self._headers))
            lines.extend(" | ".join(row) for row in self._rows)
            return "\n".join(lines)

    Console = _PlainConsole  # type: ignore[assignment]
    Table = _PlainTable  # type: ignore[assignment]

from .profile_query import (
    filter_aggregated,
    filter_raw,
    iter_aggregated_entries,
    iter_raw_entries,
    load_profile,
)

app = typer.Typer(help="Self knowledge extractor MVP")
context_app = typer.Typer(help="Personal context server commands")
app.add_typer(context_app, name="context")


@app.command()
def init_config(path: str = typer.Argument("config.yaml")) -> None:
    """Write a default config template."""
    from .config import dump_default_config

    if Path(path).exists():
        raise typer.BadParameter(f"Refusing to overwrite existing file: {path}")
    dump_default_config(path)
    print(f"[green]Created starter config at[/green] {path}")


@app.command()
def run(config: str = typer.Option("config.yaml", "--config", "-c")) -> None:
    from .config import load_config
    from .pipeline import run_pipeline

    cfg = load_config(config)
    run_pipeline(cfg)


def _parse_date(name: str, value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid {name}: {value}. Use YYYY-MM-DD.") from exc


def _format_list(values: List[str], limit: int) -> str:
    if not values:
        return ""
    clipped = values[:limit]
    remainder = len(values) - len(clipped)
    text = "; ".join(clipped)
    if remainder > 0:
        text += f" (+{remainder})"
    return text


@app.command()
def query(
    profile: Path = typer.Option(Path("output/profile.json"), "--profile", "-p"),
    bucket: Optional[str] = typer.Option(None, "--bucket", "-b"),
    search: List[str] = typer.Option([], "--search", "-s", help="Case-insensitive keywords to match."),
    require_all: bool = typer.Option(False, "--require-all", help="Require all search terms to match."),
    min_mentions: Optional[int] = typer.Option(None, "--min-mentions", help="Minimum mention count (aggregated only)."),
    after: Optional[str] = typer.Option(None, help="Filter items on/after this date (YYYY-MM-DD)."),
    before: Optional[str] = typer.Option(None, help="Filter items on/before this date (YYYY-MM-DD)."),
    include_raw: bool = typer.Option(False, "--raw", help="Include matching raw extractions."),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum aggregated results to show."),
    evidence_limit: int = typer.Option(2, "--evidence-limit", help="Max evidence snippets to display."),
) -> None:
    profile_path = profile.expanduser()
    if not profile_path.exists():
        raise typer.BadParameter(f"Profile file not found: {profile_path}")

    tokens = [token.casefold() for token in search if token]
    after_date = _parse_date("after", after)
    before_date = _parse_date("before", before)

    data = load_profile(profile_path)

    aggregated = filter_aggregated(
        iter_aggregated_entries(data),
        bucket=bucket,
        tokens=tokens,
        require_all=require_all,
        after=after_date,
        before=before_date,
        min_mentions=min_mentions,
    )

    if limit is not None:
        aggregated = aggregated[: max(limit, 0)]

    console = Console()

    table = Table(title="Aggregated Matches")
    table.add_column("Bucket", style="cyan", no_wrap=True)
    table.add_column("Text", style="white")
    table.add_column("Mentions", style="magenta", justify="right")
    table.add_column("Date", style="green", no_wrap=True)
    table.add_column("Governance", style="yellow")
    table.add_column("Evidence", style="blue")

    for entry in aggregated:
        table.add_row(
            entry.bucket,
            entry.text,
            str(entry.mentions),
            entry.last_edited_date or "",
            _format_list(entry.governance, evidence_limit),
            _format_list(entry.evidence, evidence_limit),
        )

    console.print(table)
    console.print(f"Found {len(aggregated)} aggregated matches.")

    if include_raw:
        raw_entries = filter_raw(
            iter_raw_entries(data),
            bucket=bucket,
            tokens=tokens,
            require_all=require_all,
            after=after_date,
            before=before_date,
        )
        raw_table = Table(title="Raw Matches")
        raw_table.add_column("Bucket", style="cyan", no_wrap=True)
        raw_table.add_column("Value", style="white")
        raw_table.add_column("Evidence", style="blue")
        raw_table.add_column("Governance", style="yellow")
        raw_table.add_column("Source", style="green")
        raw_table.add_column("Chunk", style="magenta", justify="right")
        raw_table.add_column("Date", style="green")

        for entry in raw_entries[: limit or len(raw_entries)]:
            raw_table.add_row(
                entry.bucket,
                entry.value,
                entry.evidence,
                entry.governance,
                entry.source,
                str(entry.chunk),
                entry.last_edited_date or "",
            )

        console.print(raw_table)
        console.print(f"Found {len(raw_entries)} raw matches.")


@context_app.command("serve")
def context_serve(
    profile: Path = typer.Option(Path("output/profile-all.json"), "--profile", "-p"),
    rules: Path = typer.Option(Path("context-rules.json"), "--rules", "-r"),
    transport: str = typer.Option(
        "http",
        "--transport",
        help="FastMCP transport to use (stdio, http, or sse).",
        case_sensitive=False,
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8077, "--port"),
    path: str = typer.Option("/mcp", "--path", help="HTTP path when using http transport."),
    embedding_model: str = typer.Option("all-MiniLM-L6-v2", "--embedding-model"),
    embedding_device: Optional[str] = typer.Option(None, "--embedding-device"),
) -> None:
    """Start the MCP server for LLM integrations."""

    profile = Path(profile)
    rules = Path(rules)
    from .context_server.mcp import ContextMCPServer

    server = ContextMCPServer(
        profile_path=profile,
        rules_path=rules,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
    )
    run_kwargs: Dict[str, Any] = {"transport": transport.lower()}
    if run_kwargs["transport"] in {"http", "sse"}:
        run_kwargs["host"] = host
        run_kwargs["port"] = port
    if run_kwargs["transport"] == "http":
        run_kwargs["path"] = path

    server.run(**run_kwargs)


@context_app.command("tui")
def context_tui(
    profile: Path = typer.Option(Path("output/profile-all.json"), "--profile", "-p"),
    rules: Path = typer.Option(Path("context-rules.json"), "--rules", "-r"),
    embedding_model: str = typer.Option("all-MiniLM-L6-v2", "--embedding-model"),
    embedding_device: Optional[str] = typer.Option(None, "--embedding-device"),
) -> None:
    """Launch the terminal UI for reviewing data and rules."""

    profile = Path(profile)
    rules = Path(rules)
    from .context_server.tui import run_tui

    run_tui(
        profile_path=profile,
        rules_path=rules,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
    )


@context_app.command("search")
def context_search(
    query: str = typer.Argument(..., help="Natural language query."),
    profile: Path = typer.Option(Path("output/profile-all.json"), "--profile", "-p"),
    rules: Path = typer.Option(Path("context-rules.json"), "--rules", "-r"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    domain: Optional[str] = typer.Option(None, "--domain"),
    tags: List[str] = typer.Option([], "--tag"),
    embedding_model: str = typer.Option("all-MiniLM-L6-v2", "--embedding-model"),
    embedding_device: Optional[str] = typer.Option(None, "--embedding-device"),
) -> None:
    """Run a search against the personal context store from the CLI."""

    profile = Path(profile)
    rules = Path(rules)
    top_k = int(top_k)
    from .context_server.search import SearchRequest
    from .context_server.service import PersonalContextService

    service = PersonalContextService(
        profile_path=profile,
        rules_path=rules,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
    )
    request = SearchRequest(query=query, top_k=top_k)
    response = service.query(request, domain=domain, tags=tags)
    console = Console()
    table = Table(title="Context Search")
    table.add_column("Score", style="magenta", justify="right")
    table.add_column("Title", style="cyan")
    table.add_column("Domain", style="green")
    table.add_column("Tags", style="yellow")
    table.add_column("Reason", style="white")
    for fact in response.shared:
        table.add_row(
            f"{fact.score:.2f}",
            fact.title,
            fact.domain,
            ", ".join(fact.tags),
            fact.search_reason,
        )
    console.print(table)
    console.print(
        f"Filtered: {len(response.filtered)} (rules: {len(response.audit.blocked_by_rules)}, sensitive: {len(response.audit.blocked_by_sensitive)})"
    )


@context_app.command("build-profile")
def context_build_profile(
    aggregated: Path = typer.Option(Path("output/profile.json"), "--aggregated", "-a"),
    output: Path = typer.Option(Path("output/profile-all.json"), "--output", "-o"),
    embedding_model: str = typer.Option("all-MiniLM-L6-v2", "--embedding-model"),
    embedding_device: Optional[str] = typer.Option(None, "--embedding-device"),
) -> None:
    """Generate profile-all.json from the aggregated profile output."""

    aggregated = Path(aggregated)
    output = Path(output)
    if not aggregated.exists():
        raise typer.BadParameter(f"Aggregated profile not found: {aggregated}")
    from .context_server.builder import ProfileBuilderError, build_profile_database

    try:
        build_profile_database(
            aggregated_profile=aggregated,
            output_path=output,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
        )
    except ProfileBuilderError as exc:
        raise typer.BadParameter(str(exc)) from exc
    print(f"[green]Wrote personal context profile to[/green] {output}")


if __name__ == "__main__":
    app()
