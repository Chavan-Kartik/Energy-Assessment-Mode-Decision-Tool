"""
Checks this tool against every number the manuscript actually states.

Run it with:  py verify.py

Three things happen. First the framework is called directly and compared against
Sections 5.1 and 5.2. Then each of the three case studies is pushed through the
web layer in app.py, to show that nothing is changed on the way in or out and
that each one reaches the disposition it is meant to demonstrate. Finally the
non-compensatory behaviour is exercised: a gate item is dropped below threshold,
an override is declared, and an entire readiness dimension is marked not
applicable.

No server needs to be running. Records are written to a scratch database so the
tool's own run history is left alone.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import storage

# Point the record store at a scratch file before app.py is used, so verifying
# the tool does not add rows to the run list shown in the interface.
storage.DB_PATH = Path(tempfile.gettempdir()) / "eaf_verify.db"
storage.DB_PATH.unlink(missing_ok=True)
storage.initialise()

import app  # noqa: E402
import cases  # noqa: E402
import reproduction  # noqa: E402

PASS, FAIL = "PASS", "*** FAIL ***"
results: list[bool] = []


def check(label: str, got, expected, tol: float = 5e-3) -> None:
    if isinstance(got, bool) or isinstance(expected, bool):
        good = got == expected
        shown = str(got)
    elif isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        good = abs(got - expected) <= tol
        shown = f"{got:.2f}"
    else:
        good = got == expected
        shown = str(got)
    results.append(good)
    print(f"  {label:<48} {shown:<28} paper: {expected}   {PASS if good else FAIL}")


def assess(case_id: str, run_key: str) -> dict:
    """Runs one stored case study through the web layer."""
    found = cases.find_run(case_id, run_key)
    assert found is not None, f"no case-study run {case_id}/{run_key}"
    _, run = found
    return app.assess(app.AssessmentIn(**run["inputs"]))


# ---------------------------------------------------------------------------
print("\nThe framework against the manuscript's stated values")
print("(this is the same check the tool reports in layer 4)\n")

for row in reproduction.checks():
    results.append(row["passed"])
    print(
        f"  [{row['section']:>10}]  {row['quantity']:<46} {str(row['got']):<22}"
        f" paper: {row['expected']}   {PASS if row['passed'] else FAIL}"
    )

# ---------------------------------------------------------------------------
print("\nCase study 3, through the web layer  (Section 5.2, EEM 54)")

result = assess("override", "onsite")
record = result["record"]

check(
    "readiness vector S",
    [round(v, 2) for v in record["readiness_vector"].values()],
    [80.0, 70.0, 75.0, 60.0, 65.0],
)
check("readiness interval, lower", record["readiness_interval"][0], 66.25)
check("readiness interval, upper", record["readiness_interval"][1], 73.75)
check("CRIS", record["cris"], 14)
check("normalized interaction R", record["normalized_interaction"], 77.78)
check("opportunity OP, z = (80, 75, 70)", record["opportunity_interval"][0], 75.0)
check("criticality AC, D = 55, C = 70, V = 90",
      record["assessment_criticality_interval"][0], 70.69)
check("disposition", record["selected_mode"], "ON-SITE EXPERT")
check("override was applied", record["override_triggered"], True)
check("a score decided the route", result["decision"]["scores_used_for_routing"], False)

# ---------------------------------------------------------------------------
print("\nCase study 2, through the web layer  (Section 5.2, lower-interaction case)")

self_run = assess("routing", "self")
remote_run = assess("routing", "remote")

check("CRIS", self_run["record"]["cris"], 6)
check("normalized interaction R", self_run["record"]["normalized_interaction"], 33.33)
check("criticality AC, D = 90, C = 25, V = 20",
      self_run["record"]["assessment_criticality_interval"][0], 22.08)
check("disposition, in-house capability", self_run["record"]["selected_mode"],
      "SELF-ASSESSMENT")
check("disposition, specialist interpretation needed",
      remote_run["record"]["selected_mode"], "REMOTE SPECIALIST")

comparison = app.compare(a=self_run["run_id"], b=remote_run["run_id"])
check("differing inputs the routing rules read",
      comparison["routing_differences"],
      ["condition / specialist_interpretation_required"])
check("readiness, hazard and criticality inputs are identical",
      [d["field"] for d in comparison["differences"] if not d["affects_routing"]],
      ["rationale"])

# ---------------------------------------------------------------------------
print("\nCase study 1, through the web layer  (Section 4.5, the readiness gate)")

held = assess("gate", "held")
cleared = assess("gate", "cleared")

check("disposition with one mandatory item unmet", held["record"]["selected_mode"],
      "READINESS IMPROVEMENT / HOLD")
check("readiness was high anyway, upper bound",
      held["record"]["readiness_interval"][1], 71.88, tol=0.01)
check("gate G", held["record"]["readiness_gate"], False)
check("disposition once the item is satisfied", cleared["record"]["selected_mode"],
      "ON-SITE EXPERT")

gate_comparison = app.compare(a=held["run_id"], b=cleared["run_id"])
check("differing inputs the routing rules read",
      gate_comparison["routing_differences"],
      ["readiness / management_commitment / Safe access authorization"])

# ---------------------------------------------------------------------------
print("\nNon-compensatory behaviour  (Section 4.5, Table 5)")

# Perfect gate, but a declared safety override with no direct-verification need.
found = cases.find_run("routing", "self")
assert found is not None
request = app.AssessmentIn(**found[1]["inputs"])
request.flags["safety_override"] = True
override = app.assess(request)
check("safety override on a passing gate", override["record"]["selected_mode"],
      "ON-SITE EXPERT")
check("the low criticality figure did not prevent it",
      override["record"]["assessment_criticality_interval"][0], 22.08)

# Every rule above the one that applied must have been evaluated and not met.
trace = override["decision"]["trace"]
applied = next(row for row in trace if row["fired"])
check("rule that applied", applied["id"], "override")
check("rules above it, all not met",
      all(row["status"] == "not met" for row in trace[: trace.index(applied)]), True)

# A whole dimension marked not applicable must be refused, not scored as zero.
request.readiness["baseline_status"] = [
    app.EvidenceIn(name="not applicable at this facility", score=None) for _ in range(3)
]
try:
    app.assess(request)
    outcome, detail = "accepted silently", ""
except Exception as error:  # noqa: BLE001
    outcome, detail = "refused", getattr(error, "detail", str(error))
check("a readiness dimension with no applicable items", outcome, "refused")
print(f"      the framework said: {detail}")

# ---------------------------------------------------------------------------
storage.DB_PATH.unlink(missing_ok=True)
print(f"\n{sum(results)} of {len(results)} checks passed.\n")
