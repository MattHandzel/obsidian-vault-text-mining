"""Lightweight vector helpers to avoid hard dependency on numpy."""

from __future__ import annotations

import hashlib
import math
import random
from typing import Iterable, List, Sequence, Tuple


def ensure_vector(values: Iterable[float]) -> Tuple[float, ...]:
    return tuple(float(value) for value in values)


def vector_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def normalize_vector(vector: Sequence[float]) -> Tuple[float, ...]:
    norm = vector_norm(vector)
    if norm == 0:
        raise ValueError("Cannot normalize zero vector")
    return ensure_vector(value / norm for value in vector)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def matrix_dot_vector(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> List[float]:
    return [dot(row, vector) for row in matrix]


def argsort_desc(values: Sequence[float]) -> List[int]:
    return sorted(range(len(values)), key=lambda idx: values[idx], reverse=True)


class DeterministicNormal:
    """Very small substitute for numpy.random.default_rng.standard_normal."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def standard_normal(self, size: int) -> List[float]:
        # Box-Muller transform using uniform samples for deterministic normals.
        results: List[float] = []
        while len(results) < size:
            u1 = self._random.random()
            u2 = self._random.random()
            r = math.sqrt(-2.0 * math.log(u1 + 1e-9))
            theta = 2.0 * math.pi * u2
            results.append(r * math.cos(theta))
            if len(results) < size:
                results.append(r * math.sin(theta))
        return results[:size]


def deterministic_embedding(text: str, dim: int) -> Tuple[float, ...]:
    digest = hashlib.sha1(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "little", signed=False)
    rng = DeterministicNormal(seed)
    vector = rng.standard_normal(dim)
    return normalize_vector(vector)
