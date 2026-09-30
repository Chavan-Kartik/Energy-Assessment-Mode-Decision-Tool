"""
Every number the manuscript states, checked against what the framework computes.

This module imports assessment_framework.py and nothing else from this project,
so both verify.py and app.py can use it without a circular import. It is the
source of the reproduction panel in the tool and of the console output from
verify.py, which means the badge shown on screen and the command-line check can
never disagree with each other.

Each check records the value the manuscript prints and the value the code
returns. Nothing is hard-coded as a result: the `got` column is always produced
by calling the framework.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import assessment_framework as af

HERE = Path(__file__).parent

def equal_weights(n: int) -> af.PreferenceSet:
    """
    A single weight vector giving every criterion the same weight.

    The last element absorbs the rounding so the vector sums to exactly 1.0 in
    binary floating point; the framework rejects a weight set that does not.
    """
    weights = [1.0 / n] * n
    weights[-1] = 1.0 - sum(weights[:-1])
    return af.PreferenceSet(
        lower=weights, upper=list(weights), label=f"equal weights (n={n})"
    )


EQUAL_5 = equal_weights(5)
BOUNDED_5 = af.PreferenceSet(lower=[0.10] * 5, upper=[0.35] * 5)
EQUAL_4 = equal_weights(4)
EQUAL_3 = equal_weights(3)

TOLERANCE = 5e-3


def _library() -> list[dict]:
    return json.loads((HERE / "eem_library.json").read_text(encoding="utf-8"))


def _agrees(got: Any, expected: Any) -> bool:
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(got) - float(expected)) <= TOLERANCE
    return got == expected


def checks() -> list[dict]:
    """
    Runs the framework against the manuscript's stated values.

    Returns one row per check: which section states it, what it states, and what
    the code returned.
    """
    library = _library()
    eem54 = next(e for e in library if e["eem_id"] == 54)

    rows: list[tuple[str, str, Any, Any]] = []

    # --- Section 5.1, readiness aggregation over an admissible weight set ------
    S = [80, 70, 75, 60, 65]
    equal = af.linear_score_envelope(S, EQUAL_5)
    bounded = af.linear_score_envelope(S, BOUNDED_5)

    rows += [
        ("5.1", "RI at equal weights", equal.minimum, 70.0),
        ("5.1", "RI lower bound, 0.10 <= w <= 0.35", bounded.minimum, 66.25),
        ("5.1", "RI upper bound, 0.10 <= w <= 0.35", bounded.maximum, 73.75),
    ]

    # --- Section 5.2, EEM 54 --------------------------------------------------
    cris54, r54 = af.compute_cris(eem54["hazard_list"])
    op54 = af.compute_opportunity_envelope([80, 75, 70], EQUAL_3)
    ac54 = af.compute_assessment_criticality_envelope(r54, 55, 70, 90, EQUAL_4)

    rows += [
        ("Appendix B", "EEM 54 hazard coding", eem54["hazard_list"], [1, 3, 1, 3, 3, 3]),
        ("5.2", "EEM 54 CRIS", cris54, 14),
        ("5.2", "EEM 54 interaction R", r54, 77.78),
        ("5.2", "EEM 54 OP, z = (80, 75, 70)", op54.minimum, 75.0),
        ("5.2", "EEM 54 AC, D = 55, C = 70, V = 90", ac54.minimum, 70.69),
    ]

    # --- Section 5.2, the lower-interaction case ------------------------------
    cris6, r6 = af.compute_cris([1, 1, 1, 1, 1, 1])
    ac6 = af.compute_assessment_criticality_envelope(r6, 90, 25, 20, EQUAL_4)

    rows += [
        ("5.2", "Lower-interaction CRIS", cris6, 6),
        ("5.2", "Lower-interaction R", r6, 33.33),
        ("5.2", "Lower-interaction AC, D = 90, C = 25, V = 20", ac6.minimum, 22.08),
    ]

    # --- Section 5.1, the whole 65-EEM dataset --------------------------------
    # The manuscript claims all 65 CRIS values were reproduced exactly. Recompute
    # each one from the Appendix B codes rather than reading the stored total.
    recomputed = [af.compute_cris(e["hazard_list"])[0] for e in library]
    mismatches = sum(
        1 for e, got in zip(library, recomputed) if got != float(e["cris"])
    )

    by_stage: dict[str, list[float]] = defaultdict(list)
    for measure, cris in zip(library, recomputed):
        by_stage[measure["stage"]].append(cris)

    rows += [
        ("5.1", "Measures in the library", len(library), 65),
        ("5.1", "CRIS values that disagree with Appendix B", mismatches, 0),
        ("5.1", "Mean CRIS, drilling", statistics.mean(by_stage["drilling"]), 8.84),
        (
            "5.1",
            "Mean CRIS, well-fluid extraction",
            statistics.mean(by_stage["well_fluid_extraction"]),
            10.00,
        ),
        (
            "5.1",
            "Mean CRIS, surface treatment",
            statistics.mean(by_stage["surface_treatment"]),
            11.19,
        ),
    ]

    return [
        {
            "section": section,
            "quantity": quantity,
            "got": round(got, 2) if isinstance(got, float) else got,
            "expected": expected,
            "passed": _agrees(got, expected),
        }
        for section, quantity, got, expected in rows
    ]


def summary() -> dict:
    rows = checks()
    passed = sum(1 for row in rows if row["passed"])
    return {
        "passed": passed,
        "total": len(rows),
        "all_passed": passed == len(rows),
        "checks": rows,
    }
