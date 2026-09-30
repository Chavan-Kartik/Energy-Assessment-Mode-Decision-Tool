"""
Web layer for assessment_framework.py.

This file performs no engineering calculation of its own. It receives the values
entered in the form, hands them to run_assessment_algorithm() exactly as
supplied, and returns what that function produced. Every number that reaches the
browser was computed by the framework at the moment the button was pressed.

Three things it does beyond passing values through, none of which touch the
arithmetic:

  * it stores each run under a sequential identifier so a screenshot can be
    traced back to a reproducible record, which Appendix D requires;
  * it restates the result as the rule ladder it came from, and refuses to
    display a ladder that disagrees with the mode the framework returned;
  * it reports the linear-programming weight vectors at each end of an interval,
    which the framework computes but the record does not carry.

Run:
    py -m uvicorn app:app --reload
    then open http://127.0.0.1:8000
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import assessment_framework as af
import cases
import checklist
import reproduction
import storage

HERE = Path(__file__).parent

# The 65 measures and their Appendix B hazard coding, used to pre-fill the form.
# These are inputs the user can change, not results.
EEM_LIBRARY: list[dict] = json.loads(
    (HERE / "eem_library.json").read_text(encoding="utf-8")
)

FRAMEWORK_PATH = HERE / "assessment_framework.py"
FRAMEWORK_SHA256 = storage.file_digest(FRAMEWORK_PATH)
FRAMEWORK_VERSION = "reference-1.1"

READINESS_BOUNDS = (0.10, 0.35)
CRITICALITY_BOUNDS = (0.15, 0.40)

storage.initialise()

app = FastAPI(title="Risk-Informed Energy Assessment")


# ---------------------------------------------------------------------------
# What the form sends
# ---------------------------------------------------------------------------

class EvidenceIn(BaseModel):
    name: str
    score: Optional[Literal[0, 1, 2]]  # null means "not applicable"
    mandatory: bool = False
    threshold: Literal[1, 2] = 2


class AssessmentIn(BaseModel):
    facility: str = ""
    assessor: str = ""
    eem_id: Optional[int] = None

    readiness: dict[str, list[EvidenceIn]]
    hazard_vector: list[Literal[0, 1, 2, 3]] = Field(min_length=6, max_length=6)

    data_sufficiency_D: float = Field(ge=0, le=100)
    action_complexity_C: float = Field(ge=0, le=100)
    verification_need_V: float = Field(ge=0, le=100)

    opportunity_scores: Optional[list[float]] = None

    readiness_weight_mode: Literal["equal", "bounded"] = "bounded"
    criticality_weight_mode: Literal["equal", "bounded"] = "equal"

    flags: dict[str, bool]
    rationale: str = ""

    # Provenance only. These record which stored case study the inputs came from
    # and take no part in the calculation.
    case_id: Optional[str] = None
    case_run_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Weight sets
# ---------------------------------------------------------------------------

def equal_weights(n: int) -> af.PreferenceSet:
    """
    A single weight vector giving every criterion the same weight.

    The last element absorbs the rounding so the vector sums to exactly 1.0 in
    binary floating point; the framework rejects a weight set that does not.
    """
    weights = [1.0 / n] * n
    weights[-1] = 1.0 - sum(weights[:-1])
    return af.PreferenceSet(
        lower=weights, upper=list(weights), label=f"equal weights (n = {n})"
    )


def bounded_weights(n: int, low: float, high: float) -> af.PreferenceSet:
    return af.PreferenceSet(
        lower=[low] * n,
        upper=[high] * n,
        label=f"{low:.2f} <= w <= {high:.2f}",
    )


def _weight_set(mode: str, n: int, bounds: tuple[float, float]) -> af.PreferenceSet:
    return equal_weights(n) if mode == "equal" else bounded_weights(n, *bounds)


# ---------------------------------------------------------------------------
# Restating a result: the gate, the rule ladder, the intervals
# ---------------------------------------------------------------------------

def _gate_detail(request: AssessmentIn) -> list[dict]:
    """
    The mandatory items and whether each met its threshold.

    This is a readback of the submitted evidence, not a second gate calculation;
    the overall verdict displayed always comes from the framework's record.
    """
    titles = {d["key"]: f"{d['symbol']} {d['title']}" for d in checklist.READINESS_CHECKLIST}
    rows = []

    for dimension, items in request.readiness.items():
        for item in items:
            if not item.mandatory:
                continue
            rows.append(
                {
                    "dimension": titles.get(dimension, dimension),
                    "name": item.name,
                    "score": item.score,
                    "threshold": item.threshold,
                    "passed": item.score is not None and item.score >= item.threshold,
                }
            )

    return rows


def _rule_trace(flags: dict[str, bool], gate_passed: bool, selected_mode: str) -> list[dict]:
    """
    The ordered rules, marked with the first one that applied.

    The ladder mirrors select_assessment_mode(). To make sure this stays a
    description rather than a second opinion, the mode implied by the rule that
    fired is compared with the mode the framework actually selected, and a
    mismatch is an error rather than a picture.
    """
    trace: list[dict] = []
    fired_index: Optional[int] = None

    for index, rule in enumerate(checklist.RULE_LADDER):
        holds = bool(rule.holds(flags, gate_passed))
        if holds and fired_index is None:
            fired_index = index
        trace.append(
            {
                "id": rule.id,
                "phase": rule.phase,
                "label": rule.label,
                "condition": rule.condition,
                "mode": rule.mode,
                "holds": holds,
                "fired": False,
                "status": "",
            }
        )

    if fired_index is None:
        raise HTTPException(500, "No mode-selection rule applied.")

    for index, row in enumerate(trace):
        row["fired"] = index == fired_index
        if index < fired_index:
            row["status"] = "not met"
        elif index == fired_index:
            row["status"] = "applied"
        else:
            row["status"] = "not reached"

    implied = checklist.RULE_LADDER[fired_index].mode
    if implied != selected_mode:
        raise HTTPException(
            500,
            "Rule trace disagrees with the framework: trace implies "
            f"{implied!r} but the framework selected {selected_mode!r}.",
        )

    return trace


def _envelope(values: list[float], preference: af.PreferenceSet) -> dict:
    """Interval plus the weight vector the linear program chose at each end."""
    result = af.linear_score_envelope(values, preference)
    return {
        "minimum": result.minimum,
        "maximum": result.maximum,
        "spread": result.maximum - result.minimum,
        "weights_at_minimum": result.weights_at_minimum,
        "weights_at_maximum": result.weights_at_maximum,
        "label": preference.label,
    }


def _analytics(request: AssessmentIn, record: dict) -> dict:
    """
    Layer 2 of the architecture: the same quantities the record carries, plus the
    weight vectors at the interval endpoints.
    """
    readiness_preference = _weight_set(
        request.readiness_weight_mode, 5, READINESS_BOUNDS
    )
    criticality_preference = _weight_set(
        request.criticality_weight_mode, 4, CRITICALITY_BOUNDS
    )

    S = [record["readiness_vector"][d] for d in af.READINESS_DIMENSIONS]
    readiness = _envelope(S, readiness_preference)

    R = record["normalized_interaction"]
    criticality_components = [
        R,
        100.0 - request.data_sufficiency_D,
        request.action_complexity_C,
        request.verification_need_V,
    ]
    criticality = _envelope(criticality_components, criticality_preference)

    opportunity = None
    if request.opportunity_scores:
        opportunity = _envelope(
            list(request.opportunity_scores),
            equal_weights(len(request.opportunity_scores)),
        )
        opportunity["scores"] = list(request.opportunity_scores)

    # The record is authoritative. These are recomputed from the same framework
    # functions, so a disagreement would mean the two paths had diverged.
    for label, computed, reported in (
        ("readiness", readiness, record["readiness_interval"]),
        ("criticality", criticality, record["assessment_criticality_interval"]),
        ("opportunity", opportunity, record["opportunity_interval"]),
    ):
        if computed is None or reported is None:
            continue
        if (
            abs(computed["minimum"] - reported[0]) > 1e-6
            or abs(computed["maximum"] - reported[1]) > 1e-6
        ):
            raise HTTPException(500, f"Recomputed {label} interval disagrees with the record.")

    symbols = {d["key"]: d for d in checklist.READINESS_CHECKLIST}

    return {
        "readiness": {
            **readiness,
            "vector": [
                {
                    "key": key,
                    "symbol": symbols[key]["symbol"],
                    "title": symbols[key]["title"],
                    "value": record["readiness_vector"][key],
                }
                for key in af.READINESS_DIMENSIONS
            ],
        },
        "hazard": {
            "domains": [
                {
                    **domain,
                    "code": record["hazard_vector"][domain["key"]],
                    "level": checklist.HAZARD_LEVELS[record["hazard_vector"][domain["key"]]],
                }
                for domain in checklist.HAZARD_DOMAINS
            ],
            "cris": record["cris"],
            "cris_maximum": 18,
            "interaction_R": R,
        },
        "opportunity": opportunity,
        "criticality": {
            **criticality,
            "components": [
                {
                    "symbol": "R",
                    "label": "Normalized hazard interaction",
                    "value": R,
                    "source": "Equation (3), from CRIS",
                },
                {
                    "symbol": "100 \u2212 D",
                    "label": "Evidence deficit",
                    "value": 100.0 - request.data_sufficiency_D,
                    "source": f"entered D = {request.data_sufficiency_D:g}",
                },
                {
                    "symbol": "C",
                    "label": "Action complexity",
                    "value": request.action_complexity_C,
                    "source": "entered",
                },
                {
                    "symbol": "V",
                    "label": "Direct-verification requirement",
                    "value": request.verification_need_V,
                    "source": "entered",
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def page() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    """Everything the form needs to render, in one request."""
    return {
        "readiness_checklist": checklist.READINESS_CHECKLIST,
        "default_evidence": checklist.default_evidence(),
        "hazard_domains": checklist.HAZARD_DOMAINS,
        "hazard_levels": checklist.HAZARD_LEVELS,
        "conditions": checklist.CONDITIONS,
        "weight_sets": {
            "readiness": {
                "bounded": f"{READINESS_BOUNDS[0]:.2f} <= w <= {READINESS_BOUNDS[1]:.2f}",
                "equal": "equal weights",
            },
            "criticality": {
                "bounded": f"{CRITICALITY_BOUNDS[0]:.2f} <= q <= {CRITICALITY_BOUNDS[1]:.2f}",
                "equal": "equal weights",
            },
        },
        "eems": [
            {
                "eem_id": e["eem_id"],
                "label": f"{e['eem_id']}. {e['measure']}",
                "measure": e["measure"],
                "equipment": e["equipment"],
                "stage": e["stage"].replace("_", " "),
                "hazard_list": e["hazard_list"],
                "note": e["implementation_note"],
                "source_refs": e["source_refs"],
            }
            for e in EEM_LIBRARY
        ],
        "case_studies": cases.index(),
        "provenance": {
            "framework_version": FRAMEWORK_VERSION,
            "framework_sha256": FRAMEWORK_SHA256,
            "measures": len(EEM_LIBRARY),
        },
    }


@app.get("/api/reproduction")
def reproduction_report() -> dict:
    """The manuscript's stated values against what the framework returns."""
    return reproduction.summary()


@app.get("/api/cases/{case_id}/runs/{run_key}/inputs")
def case_inputs(case_id: str, run_key: str) -> dict:
    """
    The stored form values for one case-study run.

    Inputs only. No result is stored for a case study, so the figures can only be
    produced by running the framework on these values.
    """
    found = cases.find_run(case_id, run_key)
    if found is None:
        raise HTTPException(404, f"No case-study run {case_id}/{run_key}.")

    case, run = found
    return {
        "case_id": case["case_id"],
        "case_title": case["title"],
        "run_key": run["run_key"],
        "label": run["label"],
        "note": run["note"],
        "expect": run["expect"],
        "provenance": case["provenance"],
        "inputs": run["inputs"],
    }


@app.post("/api/assess")
def assess(request: AssessmentIn) -> dict:
    """
    Hand the submitted values to Algorithm 1, store the record, and return it.

    Nothing is looked up or cached: the framework runs on every call.
    """
    evidence = {
        dimension: [
            af.EvidenceItem(
                name=item.name,
                score=item.score,
                mandatory=item.mandatory,
                threshold=item.threshold,
            )
            for item in items
        ]
        for dimension, items in request.readiness.items()
    }

    missing = set(checklist.CONDITION_KEYS) - set(request.flags)
    if missing:
        raise HTTPException(422, f"Missing verification conditions: {sorted(missing)}")
    flags = {key: bool(request.flags[key]) for key in checklist.CONDITION_KEYS}

    readiness_preference = _weight_set(
        request.readiness_weight_mode, 5, READINESS_BOUNDS
    )
    criticality_preference = _weight_set(
        request.criticality_weight_mode, 4, CRITICALITY_BOUNDS
    )
    opportunity_preference = (
        equal_weights(len(request.opportunity_scores))
        if request.opportunity_scores
        else None
    )

    measure = next(
        (e for e in EEM_LIBRARY if e["eem_id"] == request.eem_id), None
    )
    eem_label = (
        f"EEM {measure['eem_id']} \u2014 {measure['measure']}"
        if measure
        else "unspecified measure"
    )

    try:
        record = af.run_assessment_algorithm(
            assessment_id="unassigned",
            eem_id=eem_label,
            readiness_evidence=evidence,
            hazard_vector=request.hazard_vector,
            readiness_preference_W=readiness_preference,
            opportunity_scores=request.opportunity_scores,
            opportunity_preference_A=opportunity_preference,
            data_sufficiency_D=request.data_sufficiency_D,
            action_complexity_C=request.action_complexity_C,
            verification_need_V=request.verification_need_V,
            criticality_preference_Q=criticality_preference,
            decision_inputs_without_gate={
                **flags,
                "reviewer_rationale": request.rationale,
            },
            metadata={
                "facility": request.facility,
                "assessor": request.assessor,
                "readiness_weights": readiness_preference.label,
                "criticality_weights": criticality_preference.label,
                "framework_version": FRAMEWORK_VERSION,
            },
        )
    except (ValueError, TypeError) as error:
        # Errors raised inside the framework are input problems, not server faults.
        raise HTTPException(status_code=422, detail=str(error)) from error

    as_dict = asdict(record)
    payload = request.model_dump()

    run_id = storage.save(
        created_utc=record.timestamp_utc,
        facility=request.facility,
        assessor=request.assessor,
        eem_label=eem_label,
        case_id=request.case_id,
        case_run_key=request.case_run_key,
        selected_mode=record.selected_mode,
        override=record.override_triggered,
        gate_passed=record.readiness_gate,
        input_payload=payload,
        record=as_dict,
        framework_sha256=FRAMEWORK_SHA256,
        framework_version=FRAMEWORK_VERSION,
    )
    as_dict["assessment_id"] = run_id

    trace = _rule_trace(flags, record.readiness_gate, record.selected_mode)
    applied = next(row for row in trace if row["fired"])

    return {
        "run_id": run_id,
        "record": as_dict,
        "analytics": _analytics(request, as_dict),
        "decision": {
            "disposition": record.selected_mode,
            "phase": applied["phase"],
            "rule_applied": applied["label"],
            "override": record.override_triggered,
            "rationale": record.rationale,
            "next_actions": record.next_actions,
            "gate": {
                "passed": record.readiness_gate,
                "items": _gate_detail(request),
            },
            "trace": trace,
            "conditions": [
                {**condition, "value": flags[condition["key"]]}
                for condition in checklist.CONDITIONS
            ],
            # select_assessment_mode() takes only the gate and the seven boolean
            # conditions. OP and AC are reported for planning and are not read by
            # any routing rule, which is the non-compensatory property the
            # manuscript argues for in Section 6.5.
            "scores_used_for_routing": False,
        },
        "provenance": {
            "timestamp_utc": record.timestamp_utc,
            "framework_version": FRAMEWORK_VERSION,
            "framework_sha256": FRAMEWORK_SHA256,
            "input_sha256": storage.digest(payload),
            "readiness_weights": readiness_preference.label,
            "criticality_weights": criticality_preference.label,
            "case_id": request.case_id,
            "case_run_key": request.case_run_key,
        },
    }


@app.get("/api/runs")
def runs(limit: int = Query(40, ge=1, le=200)) -> list[dict]:
    return storage.recent(limit)


@app.get("/api/runs/{run_id}")
def run(run_id: str) -> dict:
    stored = storage.load(run_id)
    if stored is None:
        raise HTTPException(404, f"No run {run_id}.")
    return stored


@app.get("/api/runs/{run_id}/export")
def export(run_id: str) -> JSONResponse:
    stored = storage.load(run_id)
    if stored is None:
        raise HTTPException(404, f"No run {run_id}.")
    return JSONResponse(
        stored,
        headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
    )


def _flatten(payload: dict) -> dict[str, dict]:
    """
    Inputs as a flat set of readable paths, so two runs can be compared.

    Readiness items are keyed by their own names rather than by position, so an
    inserted or deleted item does not make every later item look changed.

    Each entry is marked with whether the mode-selection rules can read it.
    Algorithm 1 routes on the gate and the seven verification conditions alone, so
    only a condition or a mandatory evidence item can change a disposition.
    Everything else -- hazard ratings, D, C, V, benefit scores, weight sets, the
    reviewer's note -- moves the reported figures without moving the route.
    """
    flat: dict[str, dict] = {}

    def put(path: str, value: Any, routing: bool = False) -> None:
        flat[path] = {"value": value, "routing": routing}

    for key in ("facility", "assessor", "eem_id", "rationale"):
        put(key, payload.get(key))

    for field in (
        "data_sufficiency_D",
        "action_complexity_C",
        "verification_need_V",
        "readiness_weight_mode",
        "criticality_weight_mode",
        "opportunity_scores",
        "hazard_vector",
    ):
        put(field, payload.get(field))

    for dimension, items in (payload.get("readiness") or {}).items():
        for item in items:
            mandatory = bool(item.get("mandatory"))
            put(f"readiness / {dimension} / {item['name']}", item["score"], mandatory)
            if mandatory:
                put(
                    f"readiness / {dimension} / {item['name']} (threshold)",
                    item["threshold"],
                    True,
                )

    for key, value in (payload.get("flags") or {}).items():
        put(f"condition / {key}", value, True)

    return flat


@app.get("/api/compare")
def compare(a: str = Query(...), b: str = Query(...)) -> dict:
    """
    Two stored runs side by side, with the inputs that differ.

    Appendix D specifies a versioned data model so that changes are compared
    rather than overwritten. This is that comparison.
    """
    left, right = storage.load(a), storage.load(b)
    for run_id, stored in ((a, left), (b, right)):
        if stored is None:
            raise HTTPException(404, f"No run {run_id}.")

    flat_left, flat_right = _flatten(left["inputs"]), _flatten(right["inputs"])

    absent = {"value": None, "routing": False}
    differences = []
    for key in sorted(set(flat_left) | set(flat_right)):
        a, b = flat_left.get(key, absent), flat_right.get(key, absent)
        if a["value"] == b["value"]:
            continue
        differences.append(
            {
                "field": key,
                "a": a["value"],
                "b": b["value"],
                "affects_routing": a["routing"] or b["routing"],
            }
        )

    routing_differences = [d for d in differences if d["affects_routing"]]

    return {
        "a": {
            "run_id": left["run_id"],
            "facility": left["facility"],
            "eem_label": left["eem_label"],
            "created_utc": left["created_utc"],
            "selected_mode": left["selected_mode"],
            "gate_passed": left["gate_passed"],
            "input_sha256": left["input_sha256"],
            "record": left["record"],
        },
        "b": {
            "run_id": right["run_id"],
            "facility": right["facility"],
            "eem_label": right["eem_label"],
            "created_utc": right["created_utc"],
            "selected_mode": right["selected_mode"],
            "gate_passed": right["gate_passed"],
            "input_sha256": right["input_sha256"],
            "record": right["record"],
        },
        "identical_inputs": not differences,
        "differences": differences,
        "routing_differences": [d["field"] for d in routing_differences],
        "same_disposition": left["selected_mode"] == right["selected_mode"],
    }
