"""
Web front end for assessment_framework.py.

This file performs no engineering calculation of its own. It receives the values
typed into the form, passes them to run_assessment_algorithm() in
assessment_framework.py exactly as supplied, and returns whatever that function
produces. Every number shown in the browser is computed by the framework at the
moment the button is pressed.

Run:
    py -m uvicorn app:app --reload
    then open http://127.0.0.1:8000
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import assessment_framework as af

HERE = Path(__file__).parent

# The 65 measures and their Appendix B hazard coding, used to pre-fill the form.
# These are inputs the user can change, not results.
EEM_LIBRARY = json.loads((HERE / "eem_library.json").read_text(encoding="utf-8"))

app = FastAPI(title="Risk-Informed Energy Assessment")


# ---------------------------------------------------------------------------
# What the form sends
# ---------------------------------------------------------------------------

class EvidenceIn(BaseModel):
    name: str
    score: Optional[Literal[0, 1, 2]]  # null means "not applicable"
    mandatory: bool = False
    threshold: Literal[1, 2] = 1


class AssessmentIn(BaseModel):
    facility: str = ""
    assessor: str = ""
    eem_label: str = ""

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


# ---------------------------------------------------------------------------
# Helpers that only reshape data; they do not calculate anything
# ---------------------------------------------------------------------------

def equal_weights(n: int) -> af.PreferenceSet:
    """A single weight vector with every criterion weighted the same."""
    weights = [1.0 / n] * n
    weights[-1] = 1.0 - sum(weights[:-1])  # make the sum exactly 1.0 in binary
    return af.PreferenceSet(lower=weights, upper=list(weights), label=f"equal weights (n={n})")


def bounded_weights(n: int, low: float, high: float) -> af.PreferenceSet:
    return af.PreferenceSet(
        lower=[low] * n, upper=[high] * n, label=f"{low} <= w <= {high}"
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def page() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.get("/api/eems")
def eems() -> list[dict]:
    """The measure library, used to pre-fill the hazard ratings."""
    return [
        {
            "eem_id": e["eem_id"],
            "label": f"{e['eem_id']}. {e['measure']}",
            "measure": e["measure"],
            "equipment": e["equipment"],
            "stage": e["stage"].replace("_", " "),
            "hazard_list": e["hazard_list"],
            "note": e["implementation_note"],
        }
        for e in EEM_LIBRARY
    ]


@app.post("/api/assess")
def assess(request: AssessmentIn) -> dict:
    """
    Hand the submitted values to Algorithm 1 and return its output unchanged.

    Nothing is cached, stored, or looked up: the framework runs on every call.
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

    readiness_weights = (
        equal_weights(5)
        if request.readiness_weight_mode == "equal"
        else bounded_weights(5, 0.10, 0.35)
    )
    criticality_weights = (
        equal_weights(4)
        if request.criticality_weight_mode == "equal"
        else bounded_weights(4, 0.15, 0.40)
    )

    opportunity_weights = None
    if request.opportunity_scores:
        opportunity_weights = equal_weights(len(request.opportunity_scores))

    try:
        record = af.run_assessment_algorithm(
            assessment_id=f"EAF-{abs(hash(request.facility)) % 10000:04d}",
            eem_id=request.eem_label or "unspecified measure",
            readiness_evidence=evidence,
            hazard_vector=request.hazard_vector,
            readiness_preference_W=readiness_weights,
            opportunity_scores=request.opportunity_scores,
            opportunity_preference_A=opportunity_weights,
            data_sufficiency_D=request.data_sufficiency_D,
            action_complexity_C=request.action_complexity_C,
            verification_need_V=request.verification_need_V,
            criticality_preference_Q=criticality_weights,
            decision_inputs_without_gate={
                **request.flags,
                "reviewer_rationale": request.rationale,
            },
            metadata={
                "facility": request.facility,
                "assessor": request.assessor,
                "readiness_weights": readiness_weights.label,
                "criticality_weights": criticality_weights.label,
            },
        )
    except (ValueError, TypeError) as error:
        # Errors raised inside the framework are input problems, not server faults.
        raise HTTPException(status_code=422, detail=str(error)) from error

    return asdict(record)
