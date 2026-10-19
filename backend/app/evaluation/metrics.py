"""The numbers the slide-9 targets are judged on (plan section 8). Pure functions, unit-tested."""

import math
from collections.abc import Sequence


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Agreement between two raters beyond chance. 1.0 when they agree on everything.

    When both raters give one label to every item, chance agreement is 1 and kappa is undefined;
    we return 1.0 if they agree and 0.0 if not, so a constant criterion never looks perfect by
    accident when the raters actually differ.
    """
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    p_a, p_b = sum(a) / n, sum(b) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected) / (1 - expected)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, q in (0, 100]."""
    if not values or not 0 < q <= 100:
        raise ValueError("percentile needs values and 0 < q <= 100")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0
