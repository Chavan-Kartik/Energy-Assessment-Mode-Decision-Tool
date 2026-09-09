"""
Checks this tool against every number the manuscript actually states.

Run it with:  py verify.py

It does two things. First it calls assessment_framework.py directly and compares
against Section 5.1 and 5.2. Then it pushes the same case through app.py's own
request handler, to show that the web layer changes nothing on the way in or out.

No server needs to be running.
"""

from __future__ import annotations

import json
from pathlib import Path

import app
import assessment_framework as af

PASS, FAIL = "PASS", "*** FAIL ***"
results: list[bool] = []


def check(label: str, got, expected, tol: float = 5e-3) -> None:
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        good = abs(got - expected) <= tol
        shown = f"{got:.2f}"
    else:
        good = got == expected
        shown = str(got)
    results.append(good)
    print(f"  {label:<46} {shown:<26} paper: {expected}   {PASS if good else FAIL}")


# ---------------------------------------------------------------------------
print("\nSection 5.1  readiness aggregation, S = (80, 70, 75, 60, 65)")

S = [80, 70, 75, 60, 65]
equal = af.PreferenceSet(lower=[0.2] * 5, upper=[0.2] * 5)
bounded = af.PreferenceSet(lower=[0.10] * 5, upper=[0.35] * 5)

check("equal weights, RI", af.linear_score_envelope(S, equal).minimum, 70.0)
env = af.linear_score_envelope(S, bounded)
check("bounded 0.10-0.35, RI minimum", env.minimum, 66.25)
check("bounded 0.10-0.35, RI maximum", env.maximum, 73.75)

# ---------------------------------------------------------------------------
print("\nSection 5.2  EEM 54, rod packing maintenance and leak reduction")

library = json.loads(Path("eem_library.json").read_text(encoding="utf-8"))
eem54 = next(e for e in library if e["eem_id"] == 54)
cris, R = af.compute_cris(eem54["hazard_list"])

check("hazard vector from Appendix B", eem54["hazard_list"], [1, 3, 1, 3, 3, 3])
check("CRIS", cris, 14)
check("normalized interaction R", R, 77.78)

quarters = af.PreferenceSet(lower=[0.25] * 4, upper=[0.25] * 4)
check("opportunity OP, scores 75/75/75",
      af.compute_opportunity_envelope([75, 75, 75], app.equal_weights(3)).minimum, 75.0)

# The manuscript reports AC = 70.69 for EEM 54 but never states the D, C and V it
# used. Any inputs with (100-D) + C + V = 205 give that figure; this is one set.
check("criticality AC, D=40 C=85 V=60",
      af.compute_assessment_criticality_envelope(R, 40, 85, 60, quarters).minimum, 70.69)

print("\nSection 5.2  low-interaction case, CRIS = 6, D = 90, C = 25, V = 20")
cris6, R6 = af.compute_cris([1, 1, 1, 1, 1, 1])
check("CRIS", cris6, 6)
check("normalized interaction R", R6, 33.33)
check("criticality AC",
      af.compute_assessment_criticality_envelope(R6, 90, 25, 20, quarters).minimum, 22.08)

# ---------------------------------------------------------------------------
print("\nSame case again, but pushed through the web layer in app.py")


def evidence(applicable: int, points: int) -> list[dict]:
    """`applicable` items scored 0/1/2 summing to `points`; the first is a gate item."""
    scores, left = [], points
    for _ in range(applicable):
        scores.append(min(2, left))
        left -= scores[-1]
    assert left == 0, "target not reachable with this many items"
    return [{"name": f"evidence item {i + 1}", "score": s,
             "mandatory": i == 0, "threshold": 2} for i, s in enumerate(scores)]


# item counts chosen so each S value in the manuscript example is exactly reachable
counts = {"data_availability": (10, 16), "workforce_capability": (5, 7),
          "management_commitment": (8, 12), "baseline_status": (5, 6),
          "implementation_readiness": (10, 13)}
readiness = {dim: evidence(n, p) for dim, (n, p) in counts.items()}

request = app.AssessmentIn(
    facility="Section 5.1 example", assessor="verify.py",
    eem_label="EEM 54", readiness=readiness,
    hazard_vector=eem54["hazard_list"],
    data_sufficiency_D=40, action_complexity_C=85, verification_need_V=60,
    opportunity_scores=[75, 75, 75],
    readiness_weight_mode="bounded", criticality_weight_mode="equal",
    flags={"direct_verification_required": True, "safety_override": False,
           "digital_evidence_validated": True,
           "specialist_interpretation_required": False,
           "internal_capability_adequate": True,
           "protocol_requirements_satisfied": True,
           "unresolved_evidence_requires_field": False},
    rationale="")

record = app.assess(request)
check("readiness vector", [round(v, 2) for v in record["readiness_vector"].values()],
      [80.0, 70.0, 75.0, 60.0, 65.0])
check("RI minimum", record["readiness_interval"][0], 66.25)
check("RI maximum", record["readiness_interval"][1], 73.75)
check("AC", record["assessment_criticality_interval"][0], 70.69)
check("selected mode", record["selected_mode"], "ON-SITE EXPERT")

# ---------------------------------------------------------------------------
print("\nNon-compensatory behaviour  (Section 4.5, Table 5)")

# same case, but one mandatory item drops from 2 to 1
request.readiness["management_commitment"][0].score = 1
held = app.assess(request)
check("one mandatory item below threshold", held["selected_mode"],
      "READINESS IMPROVEMENT / HOLD")
check("readiness is still high anyway", held["readiness_interval"][1], 71.88, tol=0.01)

# perfect readiness plus a safety override
request.readiness["management_commitment"][0].score = 2
request.flags["direct_verification_required"] = False
request.flags["safety_override"] = True
override = app.assess(request)
check("safety override on passing gate", override["selected_mode"], "ON-SITE EXPERT")

# a whole dimension marked not applicable must be refused, not scored as zero
detail = ""
try:
    request.readiness["baseline_status"] = [
        app.EvidenceIn(name="n/a", score=None) for _ in range(3)]
    app.assess(request)
    outcome = "accepted silently"
except Exception as error:                                   # noqa: BLE001
    outcome = "refused"
    detail = getattr(error, "detail", str(error))
check("whole dimension not applicable", outcome, "refused")
print(f"      framework said: {detail}")

# ---------------------------------------------------------------------------
print(f"\n{sum(results)} of {len(results)} checks passed.\n")
