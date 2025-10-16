"""Self extraction package."""

__all__ = ["Config", "load_config", "run_pipeline"]


def __getattr__(name: str):  # pragma: no cover - compatibility shim
    if name in {"Config", "load_config"}:
        from .config import Config, load_config

        globals().update({"Config": Config, "load_config": load_config})
        return globals()[name]
    if name == "run_pipeline":
        from .pipeline import run_pipeline

        globals()["run_pipeline"] = run_pipeline
        return run_pipeline
    raise AttributeError(f"module 'self_extract' has no attribute {name}")
