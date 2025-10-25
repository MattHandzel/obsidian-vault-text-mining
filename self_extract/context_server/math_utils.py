"""Lightweight vector helpers to avoid hard dependency on numpy."""

from __future__ import annotations

import math
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
