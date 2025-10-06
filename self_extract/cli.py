from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from .config import Config, dump_default_config, load_config
from .profile_query import (
    filter_aggregated,
    filter_raw,
    iter_aggregated_entries,
    iter_raw_entries,
    load_profile,
)
from .pipeline import run_pipeline

app = typer.Typer(help="Self knowledge extractor MVP")


@app.command()
def init_config(path: str = typer.Argument("config.yaml")) -> None:
    """Write a default config template."""
    if Path(path).exists():
        raise typer.BadParameter(f"Refusing to overwrite existing file: {path}")
    dump_default_config(path)
    print(f"[green]Created starter config at[/green] {path}")


@app.command()
def run(config: str = typer.Option("config.yaml", "--config", "-c")) -> None:
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

if __name__ == "__main__":
    app()
