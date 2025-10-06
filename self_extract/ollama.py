from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

import requests
from rich import print as rprint


from .cache import LLMCache


class OllamaClient:
    """Minimal Ollama client for non-streaming generation."""

    def __init__(self, base_url: str, cache: Optional[LLMCache] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self._model_cache: Dict[str, bool] = {}

    def model_exists(self, model: str, *, use_cache: bool = True) -> bool:
        """Return True if the given model is available on the Ollama instance."""

        normalized = model.strip()
        if not normalized:
            return False

        if use_cache and normalized in self._model_cache:
            return self._model_cache[normalized]

        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": normalized},
                timeout=60,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to query Ollama for model '{normalized}': {exc}"
            ) from exc

        if response.status_code == 404:
            exists = False
        else:
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"Unexpected response while checking model '{normalized}': {exc}"
                ) from exc
            exists = True

        self._model_cache[normalized] = exists
        return exists

    def generate(self, model: str, prompt: str) -> str:
        if self.cache:
            cached = self.cache.get(model, prompt)
            if cached is not None:
                return cached

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        response = requests.post(
            f"{self.base_url}/api/generate", json=payload, timeout=600
        )
        response.raise_for_status()
        body = response.json()
        if "response" not in body:
            raise RuntimeError(f"Unexpected Ollama response keys: {body.keys()}")
        output = body["response"]
        if self.cache:
            self.cache.set(model, prompt, output)
        return output

    def embeddings(self, model: str, texts: Sequence[str]) -> List[List[float]]:
        payload: Dict[str, Any] = {"model": model, "input": list(texts)}
        response = requests.post(
            f"{self.base_url}/api/embeddings", json=payload, timeout=300
        )
        response.raise_for_status()
        body = response.json()
        if "embeddings" in body:
            return body["embeddings"]
        if "embedding" in body:
            embedding = body["embedding"]
            if (
                isinstance(embedding, list)
                and embedding
                and isinstance(embedding[0], list)
            ):
                return embedding
            return [embedding]
        raise RuntimeError("Unexpected embeddings response from Ollama")

    @staticmethod
    def parse_response(raw: str) -> Dict[str, Any]:
        # Primary parse attempt
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Attempt to recover by extracting the first JSON object substring
            try:
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    snippet = raw[start : end + 1]
                    return json.loads(snippet)
            except Exception:
                pass
            preview = raw[:240].replace("\n", " ") + ("…" if len(raw) > 240 else "")
            rprint(
                f"[yellow]Warning:[/yellow] Failed to parse JSON from LLM response; continuing. Preview: {preview}"
            )
            return {}
