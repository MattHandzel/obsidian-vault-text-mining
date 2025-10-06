from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

import yaml


@dataclass
class Filters:
    file_extensions: List[str] = field(default_factory=lambda: [".md"])
    min_word_count: int = 50
    max_files: int | None = 10


@dataclass
class OllamaOptions:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma3:4b-it-qat"
    aggregator_model: str = "gemma3:12-it-qat"
    embedding_model: str = "nomic-embed-text"


@dataclass
class AggregationOptions:
    similarity_threshold: float = 0.82
    embedding_batch_size: int = 32
    summary_max_items: int = 12
    enable_clustering: bool = True
    passes: int = 1
    global_context: bool = False
    enabled: bool = True


@dataclass
class ExtractionTarget:
    name: str
    description: str = ""


@dataclass
class Config:
    vault_path: Path = Path("~/notes").expanduser()
    target_folder: str = "dailies"
    input_paths: List[str] = field(default_factory=lambda: ["dailies"])
    filters: Filters = field(default_factory=Filters)
    extraction_targets: List[ExtractionTarget] = field(
        default_factory=lambda: [
            ExtractionTarget("facts", "Verifiable statements about the author."),
            ExtractionTarget("values", "Principles or priorities the author explicitly states."),
            ExtractionTarget("interests", "Topics or activities the author enjoys or pursues."),
            ExtractionTarget("skills", "Abilities the author claims or demonstrates."),
            ExtractionTarget("goals", "Specific objectives the author is working toward."),
            ExtractionTarget("habits", "Repeated behaviors or routines mentioned."),
            ExtractionTarget("beliefs", "Core beliefs or worldview statements."),
            ExtractionTarget("personality_traits", "Adjectives describing the author's character."),
            ExtractionTarget("tone", "Tone or mood of the author's writing."),
            ExtractionTarget("emotions", "Emotions the author states or implies."),
            ExtractionTarget("projects", "Named projects or initiatives the author works on."),
            ExtractionTarget("other_insights", "Notable insights that don't fit other categories."),
        ]
    )
    ollama: OllamaOptions = field(default_factory=OllamaOptions)
    aggregation: AggregationOptions = field(default_factory=AggregationOptions)
    prompts_path: Path = Path("prompts.yaml")
    output_json: Path = Path("output/profile.json")
    cache_path: Path = Path("output/cache.json")

    @property
    def scoped_path(self) -> Path:
        inputs = self.resolved_inputs
        if inputs:
            return inputs[0]
        return (self.vault_path / self.target_folder).resolve()

    @property
    def extraction_target_names(self) -> List[str]:
        return [target.name for target in self.extraction_targets]

    @property
    def resolved_inputs(self) -> List[Path]:
        entries = self.input_paths if self.input_paths else [self.target_folder]
        resolved: List[Path] = []
        seen: set[Path] = set()
        for entry in entries:
            candidate = Path(entry).expanduser()
            if not candidate.is_absolute():
                candidate = (self.vault_path / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            resolved.append(candidate)
        return resolved

    def describe_inputs(self) -> str:
        inputs = self.resolved_inputs
        if inputs:
            return ", ".join(str(path) for path in inputs)
        return str((self.vault_path / self.target_folder).resolve())


_DEFAULT_EXTRACTION_TARGETS: List[ExtractionTarget] = [
    ExtractionTarget(target.name, target.description)
    for target in Config().extraction_targets
]


def _default_target_description(name: str) -> str:
    for target in _DEFAULT_EXTRACTION_TARGETS:
        if target.name == name:
            return target.description
    return ""


def _parse_targets(raw_targets: Any) -> List[ExtractionTarget]:
    if not raw_targets:
        return [ExtractionTarget(t.name, t.description) for t in _DEFAULT_EXTRACTION_TARGETS]

    targets: List[ExtractionTarget] = []
    if isinstance(raw_targets, list):
        for entry in raw_targets:
            if isinstance(entry, str):
                targets.append(
                    ExtractionTarget(
                        entry,
                        _default_target_description(entry),
                    )
                )
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("target")
                if not name:
                    continue
                description = entry.get("description") or _default_target_description(name)
                targets.append(ExtractionTarget(name, description))

    if not targets:
        return [ExtractionTarget(t.name, t.description) for t in _DEFAULT_EXTRACTION_TARGETS]
    return targets


def _deep_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert nested dataclasses to dicts for yaml serialization."""
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if hasattr(value, "__dataclass_fields__"):
            out[key] = _deep_dict(value.__dict__)
        else:
            out[key] = value
    return out


def load_config(path: str | Path) -> Config:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    filters = Filters(**raw.get("filters", {}))
    ollama = OllamaOptions(**raw.get("ollama", {}))
    aggregation = AggregationOptions(**raw.get("aggregation", {}))
    targets = _parse_targets(raw.get("extraction_targets"))
    input_paths_raw = raw.get("input_paths")
    if isinstance(input_paths_raw, list):
        input_paths = [str(path) for path in input_paths_raw]
    elif input_paths_raw:
        input_paths = [str(input_paths_raw)]
    else:
        input_paths = []

    cfg = Config(
        vault_path=Path(raw.get("vault_path", Config.vault_path)).expanduser(),
        target_folder=raw.get("target_folder", Config.target_folder),
        input_paths=input_paths if input_paths else [raw.get("target_folder", Config.target_folder)],
        filters=filters,
        extraction_targets=targets,
        ollama=ollama,
        aggregation=aggregation,
        prompts_path=Path(raw.get("prompts_path", Config.prompts_path)),
        output_json=Path(raw.get("output_json", Config.output_json)),
        cache_path=Path(raw.get("cache_path", Config.cache_path)).expanduser(),
    )
    return cfg


def dump_default_config(path: str | Path) -> None:
    cfg = Config()
    data = {
        "vault_path": str(cfg.vault_path),
        "target_folder": cfg.target_folder,
        "input_paths": cfg.input_paths,
        "filters": _deep_dict(cfg.filters.__dict__),
        "extraction_targets": [
            {"name": target.name, "description": target.description}
            for target in cfg.extraction_targets
        ],
        "ollama": _deep_dict(cfg.ollama.__dict__),
        "aggregation": _deep_dict(cfg.aggregation.__dict__),
        "prompts_path": str(cfg.prompts_path),
        "output_json": str(cfg.output_json),
        "cache_path": str(cfg.cache_path),
    }
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
