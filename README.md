# Self Knowledge Extraction MVP

Simple pipeline that walks a portion of an Obsidian vault (defaults to `~/notes/dailies`), sends chunks of the notes to a local Ollama model, and aggregates the returned persona facts into `output/profile.json`.

```mermaid
flowchart LR
  A[Scan notes: notes/dailies] --> B{Filter}
  B -->|.md + min words + max files| C[Chunk notes]
  C --> D[Extract facts with Ollama]
  D --> E{Aggregation enabled}
  E -- No --> G[Write raw_extractions]
  E -- Yes --> F[Embed + cluster + reconcile + summarize]
  F --> H{Global context}
  H -- Yes --> I[Attach global_context]
  H -- No --> J[Skip]
  D --> L[Write profile.runs.jsonl]
  G --> K[Write profile.json]
  F --> K
  I --> K
  K --> M[Query CLI: bucket / search / raw]
```

## Quick start

```bash
cd /home/matth/Projects/SelfKnowledgeExtraction
# nix-shell # if you have nix installed
python -m self_extract.cli init-config  # creates config.yaml
# edit config.yaml if needed (e.g. different ollama host or folder limit)
python -m self_extract.cli run -c config.yaml
exit  # leave the nix shell when you are done
```

To inspect the merged profile:

```bash
python -m self_extract.cli query --profile output/profile.json --bucket goals --search "exercise" --raw
```

The run command processes the first N markdown files (default 10) in `~/notes/dailies`, skipping notes shorter than 50 words. Results go to `output/profile.json` (bucket objects with canonical `items`, `summary`, and optional `_global_context`) and a per-chunk log in `output/profile.runs.jsonl`.

## Personal Context Server

The Personal Context Server exposes the consolidated profile to local LLM agents via the Model Context Protocol (MCP) and provides a terminal UI for managing sharing rules.

1. Build the context database (computes embeddings) from the latest aggregated profile:

   ```bash
   python -m self_extract.cli context build-profile \
     --aggregated output/profile.json \
     --output output/profile-all.json
   ```

2. (Optional) Seed rules from `context-rules.example.json`:

   ```bash
   cp context-rules.example.json context-rules.json
   ```

3. Launch the MCP server for downstream tools:

   ```bash
   python -m self_extract.cli context serve --profile output/profile-all.json --rules context-rules.json
   ```

4. Inspect and edit rules in the TUI:

   ```bash
   python -m self_extract.cli context tui --profile output/profile-all.json --rules context-rules.json
   ```

The CLI also exposes `python -m self_extract.cli context search "query"` for quick checks. All commands run offline by default and reuse the `sentence-transformers` model specified via `--embedding-model`.

## Configuration

`config.yaml` keys:

- `vault_path`: Base path of your Obsidian vault (defaults to `~/notes`).
- `target_folder`: Folder inside the vault to scan (defaults to `dailies`).
- `input_paths`: List of folders or individual files (relative to the vault or absolute) to process; defaults to `["dailies"]` for backward compatibility.
- `filters.file_extensions`: File extensions to include (defaults to `.md`).
- `filters.min_word_count`: Minimum words per note for extraction.
- `filters.max_files`: Cap on number of notes processed per run (defaults to 10 for a quick MVP pass).
- `ollama.base_url`: Where your Ollama server is running.
- `ollama.model`: Model ID to call for chunk extraction (defaults to `gemma3:4b-it-qat`).
- `ollama.aggregator_model`: Model used to reconcile items across notes (defaults to `gemma3:12-it-qat`).
- `ollama.embedding_model`: Embedding model for semantic clustering before aggregation (defaults to `nomic-embed-text`).
- `aggregation.similarity_threshold`: Cosine similarity cut-off when grouping facts.
- `aggregation.embedding_batch_size`: Batch size for embedding calls.
- `aggregation.summary_max_items`: Maximum canonical items to feed into the summariser per bucket.
- `aggregation.enable_clustering`: Toggle semantic clustering (defaults to `true`).
- `aggregation.passes`: Number of aggregation passes to run (defaults to `1`).
- `aggregation.global_context`: If `true`, generates a vault-wide context summary between passes.
- `aggregation.enabled`: Master switch for aggregation; set `false` or `passes: 0` to emit raw results without consolidation.
- `prompts_path`: Location of `prompts.yaml`, which holds every prompt template.
- `extraction_targets`: Buckets to request from the model; each target can include a `name` and optional `description` used in prompts. Only these targets appear in the extraction schema sent to the LLM.
- `output_json`: Path for the merged JSON report.
- `cache_path`: Where the LLM response cache is stored; identical prompts on the same model reuse cached outputs.

## Notes

- Frontmatter `last_edited_date` (fallbacks: `last_edited_at`, `updated_at`, `modified`, `created_*`) timestamps extractions; make sure your notes include one of them.
- Semantic clustering keeps related facts together before the aggregator LLM resolves conflicts and writes summaries.
- Prompts live in `prompts.yaml`; tweak templates there (cluster/summary/global context). Use `{{PLACEHOLDER}}` syntax.
- Logs are kept alongside the JSON to make it easy to review how many items each chunk contributed.
- When `aggregation.global_context` is true, `_global_context` is added to the JSON with a long-form summary for downstream use.
- The output now stores `raw_extractions` (per chunk, pre-aggregation) and aggregated bucket entries enriched with `mentions`, `evidence`, and `governance` trails.
- Re-running the pipeline with unchanged prompts/model reuses cached LLM responses for faster execution.
- Use `python -m self_extract.cli query` to treat the profile like a lightweight database: filter by bucket, keywords, mention counts, or date ranges and optionally inspect raw chunk-level evidence.
