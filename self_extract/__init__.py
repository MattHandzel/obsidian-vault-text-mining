"""Self extraction package."""

__all__ = [
    "Config",
    "load_config",
    "run_pipeline",
]

from .config import Config, load_config  # noqa: E402,F401
from .pipeline import run_pipeline  # noqa: E402,F401
