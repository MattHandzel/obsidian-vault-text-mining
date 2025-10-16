# Personal Context Server Architecture (draft)

## Data layer
- `profile-all.json` validated by `jsonschema`; schema stored in `self_extract/context_server/schema.py`.
- Document root: `{ "facts": [Fact], "metadata": {"generated_at": ..., "version": ...} }`.
- `Fact` fields: `id`, `title`, `summary`, `domain`, `tags`, `sensitivity` (`level`, `reasons`), `source`, `last_updated`, `embedding` (list[float]).
- `KnowledgeBase` loads JSON once, builds indexes, caches numpy arrays for embeddings, and exposes iterators plus `search_fuzzy` and `search_semantic` calls.

## Search layer
- Fuzzy search uses `rapidfuzz.process.extract` against `title`, `summary`, `tags`, `domain`. Threshold configurable (default 80) and returns scored matches.
- Semantic search encodes queries using a local `SentenceTransformer`. Facts reuse stored embeddings. Similarities computed with cosine via numpy.
- Combined search merges results and enriches with fact metadata before filtering.

## Rule engine
- Rule storage file `context-rules.json` with schema `[Rule]`.
- `Rule` dataclass: `id`, `action` (`allow`/`deny`), `kind` (`pattern`/`semantic`), `patterns`, `tags`, `domain`, `threshold`, `scope`.
- Pattern rules compile regex or fuzzy tokens. Semantic rules pre-compute embeddings for labels or example sentences.
- `RuleEngine.apply(facts, query_context)` returns two sets: `allowed` and `blocked`, respecting first-match precedence (deny overrides allow).

## Sensitive filter
- Static `SensitiveClassifier` fed with keyword sets, regex patterns, and semantic centroids (`medical`, `sexual`, `opinions`).
- Runs after rule engine; flagged items forced to `blocked` and annotated with reasons. Audit view draws from this classifier cache.

## MCP server
- Async `ContextMCPServer` implementing minimal Model Context Protocol over JSON-RPC via websockets or stdin/stdout (configurable). Tools:
  - `search_facts`: fuzzy+semantic search with filtering.
  - `list_rules`: returns rule metadata.
  - `preview_query`: dry-run query showing shareable vs blocked IDs.
- Responses include metadata describing fields and filters applied.

## TUI
- Built with `textual` and composed of screens: `DashboardScreen`, `RuleManagerScreen`, `PreviewScreen`, `SensitiveAuditScreen`.
- Shared `AppState` holds knowledge base snapshot, rule list, and audit cache; persisted edits saved to disk immediately.
- Dashboard summarises fact counts, domains, tag frequency, and recent query log.

## Logging
- `ContextLogger` writes JSON lines to `output/context-server.log` capturing timestamps, query term hashes, and counts of shared vs blocked facts (never the data itself).
