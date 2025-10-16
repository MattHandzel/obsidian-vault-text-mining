"""Textual TUI for managing the personal context server."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Log,
    Static,
    TabbedContent,
    TabPane,
)

from .rules import Rule, RuleAction, RuleKind
from .service import PersonalContextResponse, PersonalContextService
from .search import SearchRequest


class DashboardView(Static):
    """Displays high-level metrics about the knowledge base."""

    def __init__(self, service: PersonalContextService) -> None:
        super().__init__()
        self._service = service

    def on_mount(self) -> None:
        kb = self._service.knowledge_base
        domains: dict[str, int] = {}
        tags: dict[str, int] = {}
        for fact in kb.iter_facts():
            domains[fact.domain] = domains.get(fact.domain, 0) + 1
            for tag in fact.tags:
                tags[tag] = tags.get(tag, 0) + 1
        summary_lines = [
            f"Facts loaded: {len(kb)}",
            f"Rules configured: {len(self._service.rule_engine.rules())}",
            f"Unique domains: {len(domains)}",
            f"Top tags: {', '.join(sorted(tags, key=tags.get, reverse=True)[:5]) or '—'}",
        ]
        self.update("\n".join(summary_lines))


class RuleManagerView(Vertical):
    """Manage allow/deny rules from the terminal UI."""

    class RuleChanged(Message):
        def __init__(self, sender: "RuleManagerView") -> None:
            super().__init__()
            self.sender = sender

    def __init__(self, service: PersonalContextService) -> None:
        super().__init__()
        self._service = service
        self.table = DataTable(id="rule-table", zebra_stripes=True)
        self.description_input = Input(placeholder="description")
        self.pattern_input = Input(placeholder="pattern or label")
        self.domain_input = Input(placeholder="domains (comma separated)")
        self.tags_input = Input(placeholder="tags (comma separated)")
        self.threshold_input = Input(placeholder="threshold (0-1, default 0.85)")
        self.action = RuleAction.DENY
        self.kind = RuleKind.PATTERN

    def compose(self) -> ComposeResult:
        yield Static("Rules", id="rule-title")
        self.table.add_columns("Action", "Kind", "Description")
        yield self.table
        with Horizontal(id="rule-actions"):
            yield Button("Allow", id="rule-allow")
            yield Button("Deny", id="rule-deny")
            yield Button("Pattern", id="rule-pattern")
            yield Button("Semantic", id="rule-semantic")
            yield Button("Delete", id="rule-delete", variant="error")
        yield self.description_input
        yield self.pattern_input
        yield self.domain_input
        yield self.tags_input
        yield self.threshold_input
        yield Button("Save Rule", id="rule-save", variant="primary")

    def on_mount(self) -> None:
        self.refresh_table()

    def refresh_table(self) -> None:
        self.table.clear()
        for rule in self._service.rule_engine.rules():
            self.table.add_row(rule.action.value, rule.kind.value, rule.description, key=rule.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "rule-allow": RuleAction.ALLOW,
            "rule-deny": RuleAction.DENY,
        }
        if event.button.id in mapping:
            self.action = mapping[event.button.id]
            return
        if event.button.id == "rule-pattern":
            self.kind = RuleKind.PATTERN
            return
        if event.button.id == "rule-semantic":
            self.kind = RuleKind.SEMANTIC
            return
        if event.button.id == "rule-delete":
            self._delete_selected()
            return
        if event.button.id == "rule-save":
            self._save_rule()

    def _save_rule(self) -> None:
        token = self.pattern_input.value.strip()
        if not token:
            self.app.bell()
            return
        description = self.description_input.value.strip()
        domains = [value.strip() for value in self.domain_input.value.split(",") if value.strip()]
        tags = [value.strip() for value in self.tags_input.value.split(",") if value.strip()]
        threshold_value = self.threshold_input.value.strip()
        threshold = float(threshold_value) if threshold_value else 0.85
        kwargs: dict[str, List[str] | float | str] = {
            "description": description,
            "domains": domains,
            "tags": tags,
            "threshold": threshold,
        }
        if self.kind is RuleKind.PATTERN:
            kwargs["patterns"] = [token]
        else:
            kwargs["labels"] = [token]
        rule = Rule.new(action=self.action, kind=self.kind, **kwargs)
        self._service.rule_engine.upsert_rule(rule)
        self.refresh_table()
        self.post_message(self.RuleChanged(self))
        self.description_input.value = ""
        self.pattern_input.value = ""
        self.threshold_input.value = ""

    def _delete_selected(self) -> None:
        row_key = self.table.cursor_row
        if row_key is None:
            self.app.bell()
            return
        if self._service.rule_engine.delete_rule(str(row_key)):
            self.refresh_table()
            self.post_message(self.RuleChanged(self))


class PreviewView(Vertical):
    """Allow the user to trial queries and inspect filtering results."""

    class PreviewCompleted(Message):
        def __init__(self, sender: "PreviewView", response: PersonalContextResponse) -> None:
            super().__init__()
            self.sender = sender
            self.response = response

    def __init__(self, service: PersonalContextService) -> None:
        super().__init__()
        self._service = service
        self.query_input = Input(placeholder="enter query text")
        self.domain_input = Input(placeholder="domain (optional)")
        self.tags_input = Input(placeholder="tags (comma separated)")
        self.results_table = DataTable(id="preview-results", zebra_stripes=True)
        self.filtered_log = Log(id="filtered-log")

    def compose(self) -> ComposeResult:
        yield Static("Preview Mode", id="preview-title")
        yield self.query_input
        yield self.domain_input
        yield self.tags_input
        yield Button("Run Preview", id="preview-run", variant="primary")
        self.results_table.add_columns("Score", "Title", "Domain", "Tags", "Reason")
        yield self.results_table
        yield Static("Filtered IDs", id="filtered-title")
        yield self.filtered_log

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "preview-run":
            return
        query = self.query_input.value.strip()
        if not query:
            self.app.bell()
            return
        tags = [value.strip() for value in self.tags_input.value.split(",") if value.strip()]
        domain = self.domain_input.value.strip() or None
        request = SearchRequest(query=query)
        response = self._service.query(request, domain=domain, tags=tags)
        self._render_response(response)
        self.post_message(self.PreviewCompleted(self, response))

    def _render_response(self, response: PersonalContextResponse) -> None:
        self.results_table.clear()
        for fact in response.shared:
            self.results_table.add_row(
                f"{fact.score:.2f}",
                fact.title,
                fact.domain,
                ", ".join(fact.tags),
                fact.search_reason,
            )
        self.filtered_log.clear()
        for item in response.filtered:
            self.filtered_log.write(item)


class SensitiveAuditView(Vertical):
    """Display facts flagged as sensitive by the classifier."""

    def __init__(self, service: PersonalContextService) -> None:
        super().__init__()
        self._service = service
        self.table = DataTable(id="audit-table", zebra_stripes=True)

    def compose(self) -> ComposeResult:
        yield Static(
            "Sensitive Data Audit (read-only). Use the Rules tab to allow/deny specific matches.",
            id="audit-title",
        )
        self.table.add_columns("Fact ID", "Title", "Reasons")
        yield self.table

    def on_mount(self) -> None:
        decision = self._service.sensitive_filter.evaluate(self._service.knowledge_base.facts())
        for fact in decision.blocked:
            reasons = decision.reasons.get(fact.id, [])
            self.table.add_row(fact.id, fact.title, ", ".join(reasons))


class ContextApp(App[None]):
    CSS = """
    #rule-actions { height: 3; }
    #preview-results { height: 12; }
    #filtered-log { height: 6; }
    #audit-table { height: 16; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
    ]

    def __init__(
        self,
        profile_path: Path,
        rules_path: Path,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_device: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._service = PersonalContextService(
            profile_path=profile_path,
            rules_path=rules_path,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
        )
        self.audit_log: List[PersonalContextResponse] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Dashboard"):
                yield DashboardView(self._service)
            with TabPane("Rules"):
                yield RuleManagerView(self._service)
            with TabPane("Preview"):
                yield PreviewView(self._service)
            with TabPane("Audit"):
                yield SensitiveAuditView(self._service)
        yield Footer()

    def action_reload(self) -> None:
        self._service.reload()
        self.refresh(layout=True)

    def on_preview_view_preview_completed(self, message: PreviewView.PreviewCompleted) -> None:
        self.audit_log.append(message.response)


def run_tui(
    profile_path: Path,
    rules_path: Path,
    embedding_model: str = "all-MiniLM-L6-v2",
    embedding_device: Optional[str] = None,
) -> None:
    """Bootstrap the textual application."""

    app = ContextApp(
        profile_path=profile_path,
        rules_path=rules_path,
        embedding_model=embedding_model,
        embedding_device=embedding_device,
    )
    app.run()
