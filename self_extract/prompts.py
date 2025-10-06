from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import yaml


@dataclass
class Prompts:
    templates: Dict[str, str]

    def render(self, key: str, **replacements: str) -> str:
        if key not in self.templates:
            raise KeyError(f"Prompt template '{key}' not found")
        template = self.templates[key]
        for name, value in replacements.items():
            placeholder = f"{{{{{name}}}}}"
            template = template.replace(placeholder, value)
        return template


def load_prompts(path: str | Path) -> Prompts:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    with prompt_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("prompts.yaml must contain a mapping of prompt keys to templates")
    templates = {key: str(value) for key, value in data.items()}
    return Prompts(templates=templates)
