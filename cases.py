"""
The three case studies, stored as inputs only.

Each run below is a set of form values. No result is stored here and none is
precomputed: loading a case fills the form, and the numbers appear only after
assessment_framework.py has been run on those values. That is the point of
keeping this file to inputs -- a reviewer can reload any case study, press the
button, and get the figure back from the framework rather than from a cache.

Where a value is stated in the manuscript it is used verbatim, so the tool
reproduces the published example rather than a lookalike. Values the manuscript
does not state are marked `illustrative` in the `provenance` note and are
facility inputs the assessment team would supply.
"""

from __future__ import annotations

from typing import Optional

from checklist import READINESS_CHECKLIST, default_conditions

# Evidence scores, in checklist order, one list per dimension.
# 0 absent, 1 partial or outdated, 2 current and demonstrated, None not applicable.
#
# The item sets below were chosen so that Equation (4) returns exactly the
# readiness vector used in Section 5.1, S = (80, 70, 75, 60, 65). That makes the
# screenshots directly comparable with the manuscript. Two items are marked not
# applicable rather than zero, which is the distinction Appendix D requires:
# "weather or throughput normalization" is qualified "where relevant" in
# Appendix C, and this facility had no major changes in the baseline period.

_STATION_7_SCORES: dict[str, list[Optional[int]]] = {
    "data_availability": [2, 2, 2, 2, 2, 2, 1, 1, 1, 1],           # 16 / 20 -> 80.00
    "workforce_capability": [2, 2, 1, None, 1, 1],                 #  7 / 10 -> 70.00
    "management_commitment": [2, 2, 2, 1, 2, 1, 1, 1],             # 12 / 16 -> 75.00
    "baseline_status": [2, 1, 1, 1, None, 1, None],                #  6 / 10 -> 60.00
    "implementation_readiness": [2, 2, 1, 1, 1, 2, 1, 1, 1],       # with the added item below
}

# Section 4.5 requires the team to define its own item set, so this facility adds
# one item that Appendix C does not list but that governs whether rod-packing work
# can actually proceed.
_STATION_7_EXTRA: dict[str, list[tuple[str, int]]] = {
    "implementation_readiness": [("Spares availability for the affected equipment", 1)],
}

# A well-instrumented drilling support utility group. All four mandatory items are
# fully demonstrated, so the gate passes and Phase 2 is reached.
_PAD_12_SCORES: dict[str, list[Optional[int]]] = {
    "data_availability": [2, 2, 2, 2, 2, 2, 2, 2, 1, 1],           # 18 / 20 -> 90.00
    "workforce_capability": [2, 2, 2, 2, 1, 1],                    # 10 / 12 -> 83.33
    "management_commitment": [2, 2, 2, 2, 2, 2, 1, 1],             # 14 / 16 -> 87.50
    "baseline_status": [2, 2, 2, 2, 2, 1, 1],                      # 12 / 14 -> 85.71
    "implementation_readiness": [2, 2, 2, 2, 2, 2, 1, 1, 1],       # 15 / 18 -> 83.33
}


def _evidence(
    scores: dict[str, list[Optional[int]]],
    extra: Optional[dict[str, list[tuple[str, int]]]] = None,
    lower: Optional[dict[str, int]] = None,
) -> dict[str, list[dict]]:
    """
    Builds a readiness payload by pairing the checklist with a score list.

    `lower` overrides a single item by index, which is how the held and cleared
    variants of case study 1 differ from each other by exactly one value.
    """
    payload: dict[str, list[dict]] = {}

    for dimension in READINESS_CHECKLIST:
        key = dimension["key"]
        values = list(scores[key])

        if lower and key in lower:
            values[lower[key]] = 1

        if len(values) != len(dimension["items"]):
            raise ValueError(
                f"{key}: {len(values)} scores for {len(dimension['items'])} items."
            )

        rows = [
            {"name": name, "score": score, "mandatory": mandatory, "threshold": 2}
            for (name, mandatory), score in zip(dimension["items"], values)
        ]

        for name, score in (extra or {}).get(key, []):
            rows.append(
                {"name": name, "score": score, "mandatory": False, "threshold": 2}
            )

        payload[key] = rows

    return payload


def _conditions(**overrides: bool) -> dict[str, bool]:
    flags = default_conditions()
    unknown = set(overrides) - set(flags)
    if unknown:
        raise ValueError(f"Unknown condition keys: {sorted(unknown)}")
    flags.update(overrides)
    return flags


# ---------------------------------------------------------------------------
# Case study 1: the facility-level gate
# ---------------------------------------------------------------------------

_CASE_1 = {
    "case_id": "gate",
    "number": 1,
    "title": "A site that looks ready and still cannot be assessed",
    "question": "Can we even study this yet?",
    "demonstrates": (
        "The Phase 1 readiness gate, Equation (7). One mandatory evidence item is "
        "only partly satisfied. Readiness still aggregates to a respectable interval, "
        "and the tool returns a hold rather than an assessment mode, because a "
        "favourable aggregate cannot substitute for a missing prerequisite."
    ),
    "layman": (
        "A hospital cannot operate until consent is signed. However good the rest of "
        "the paperwork is, the answer is not 'send a surgeon', it is 'go and get "
        "consent'."
    ),
    "paper_reference": "Section 4.5, Equation (7), Table 5 row 4",
    "runs": [
        {
            "run_key": "held",
            "label": "Safe access authorization only partly satisfied",
            "note": (
                "A permit exists for the station but not for the compressor deck, so "
                "the item is coded 1 rather than 2 and falls below its threshold."
            ),
            "expect": "READINESS IMPROVEMENT / HOLD",
            "inputs": {
                "facility": "Gas gathering station 7 (illustrative)",
                "assessor": "EAF assessment team",
                "eem_id": 54,
                "readiness": _evidence(
                    _STATION_7_SCORES,
                    _STATION_7_EXTRA,
                    lower={"management_commitment": 0},
                ),
                "hazard_vector": [1, 3, 1, 3, 3, 3],
                "data_sufficiency_D": 55,
                "action_complexity_C": 70,
                "verification_need_V": 90,
                "opportunity_scores": [80, 75, 70],
                "readiness_weight_mode": "bounded",
                "criticality_weight_mode": "equal",
                "flags": _conditions(
                    direct_verification_required=True,
                    digital_evidence_validated=True,
                    internal_capability_adequate=True,
                    protocol_requirements_satisfied=True,
                ),
                "rationale": (
                    "Deck access permit covers the station boundary only; compressor "
                    "deck authorization is outstanding."
                ),
            },
        },
        {
            "run_key": "cleared",
            "label": "Same site once deck access is authorized",
            "note": (
                "Identical to the run above except that the one mandatory item now "
                "scores 2. Nothing else changes."
            ),
            "expect": "ON-SITE EXPERT",
            "inputs": {
                "facility": "Gas gathering station 7 (illustrative)",
                "assessor": "EAF assessment team",
                "eem_id": 54,
                "readiness": _evidence(_STATION_7_SCORES, _STATION_7_EXTRA),
                "hazard_vector": [1, 3, 1, 3, 3, 3],
                "data_sufficiency_D": 55,
                "action_complexity_C": 70,
                "verification_need_V": 90,
                "opportunity_scores": [80, 75, 70],
                "readiness_weight_mode": "bounded",
                "criticality_weight_mode": "equal",
                "flags": _conditions(
                    direct_verification_required=True,
                    digital_evidence_validated=True,
                    internal_capability_adequate=True,
                    protocol_requirements_satisfied=True,
                ),
                "rationale": "Compressor deck access authorization issued and recorded.",
            },
        },
    ],
    "provenance": (
        "Hazard ratings are the published Appendix B coding for EEM 54. D, C and V "
        "are the values stated for EEM 54 in Section 5.2. The evidence item scores "
        "are illustrative and were chosen so that Equation (4) reproduces the "
        "Section 5.1 readiness vector."
    ),
}


# ---------------------------------------------------------------------------
# Case study 2: which of the three modes, and why
# ---------------------------------------------------------------------------

_CASE_2 = {
    "case_id": "routing",
    "number": 2,
    "title": "Two runs of the same measure that route to different people",
    "question": "Who should do the study?",
    "demonstrates": (
        "The mode follows the state of the evidence, not the hazard score. Both runs "
        "have identical readiness, identical hazard ratings, and identical criticality "
        "inputs. One condition differs, and the work moves from the site's own "
        "engineers to a remote specialist."
    ),
    "layman": (
        "Triage. The same complaint is handled by the practice nurse or referred to a "
        "specialist depending on whether anyone on site can read the results, not on "
        "how serious the complaint sounds."
    ),
    "paper_reference": "Section 5.2, Table 5 rows 2 and 3",
    "runs": [
        {
            "run_key": "self",
            "label": "Site engineers can interpret the data themselves",
            "note": (
                "Validated data, adequate in-house capability, internal protocol "
                "satisfied, no specialist interpretation needed."
            ),
            "expect": "SELF-ASSESSMENT",
            "inputs": {
                "facility": "Drilling support utilities, pad 12 (illustrative)",
                "assessor": "EAF assessment team",
                "eem_id": 16,
                "readiness": _evidence(_PAD_12_SCORES),
                "hazard_vector": [1, 1, 1, 1, 1, 1],
                "data_sufficiency_D": 90,
                "action_complexity_C": 25,
                "verification_need_V": 20,
                "opportunity_scores": [70, 65, 60],
                "readiness_weight_mode": "bounded",
                "criticality_weight_mode": "equal",
                "flags": _conditions(
                    digital_evidence_validated=True,
                    internal_capability_adequate=True,
                    protocol_requirements_satisfied=True,
                ),
                "rationale": (
                    "Dryer cycle and discharge pressure trends are metered and the "
                    "site engineer has run this calculation before."
                ),
            },
        },
        {
            "run_key": "remote",
            "label": "Same data, but the regeneration cycle needs a specialist",
            "note": (
                "The single change is that specialist interpretation is now required. "
                "Every other input is byte-identical to the run above."
            ),
            "expect": "REMOTE SPECIALIST",
            "inputs": {
                "facility": "Drilling support utilities, pad 12 (illustrative)",
                "assessor": "EAF assessment team",
                "eem_id": 16,
                "readiness": _evidence(_PAD_12_SCORES),
                "hazard_vector": [1, 1, 1, 1, 1, 1],
                "data_sufficiency_D": 90,
                "action_complexity_C": 25,
                "verification_need_V": 20,
                "opportunity_scores": [70, 65, 60],
                "readiness_weight_mode": "bounded",
                "criticality_weight_mode": "equal",
                "flags": _conditions(
                    digital_evidence_validated=True,
                    specialist_interpretation_required=True,
                    internal_capability_adequate=True,
                    protocol_requirements_satisfied=True,
                ),
                "rationale": (
                    "Desiccant regeneration behaviour at reduced dew point needs "
                    "vendor engineering review before a setpoint is changed."
                ),
            },
        },
    ],
    "provenance": (
        "Hazard ratings are the published Appendix B coding for EEM 16, which sums to "
        "the CRIS = 6 used for the lower-interaction case in Section 5.2. D = 90, "
        "C = 25 and V = 20 are the values stated there. The opportunity scores and "
        "evidence item scores are illustrative facility inputs; the manuscript states "
        "no opportunity values for this case."
    ),
}


# ---------------------------------------------------------------------------
# Case study 3: why a strong business case cannot buy its way out
# ---------------------------------------------------------------------------

_CASE_3 = {
    "case_id": "override",
    "number": 3,
    "title": "The most attractive measure on the site still requires a site visit",
    "question": "Why can't a strong business case avoid the trip?",
    "demonstrates": (
        "Opportunity Priority and Assessment Criticality are computed, reported, and "
        "then not consulted. The mode-selection rules read only the gate and the "
        "verification conditions, so a high OP cannot trade against a direct-"
        "verification requirement. This run reproduces every number the manuscript "
        "publishes for EEM 54."
    ),
    "layman": (
        "You cannot diagnose a leak over email. However strong the business case is, "
        "somebody has to stand next to the machine and measure it."
    ),
    "paper_reference": "Section 5.2, Section 6.5, Table 5 row 1",
    "runs": [
        {
            "run_key": "onsite",
            "label": "EEM 54, reciprocating compressor rod packing",
            "note": (
                "The manuscript's worked example: CRIS 14, R 77.78, OP 75.00, "
                "AC 70.69, readiness interval [66.25, 73.75]."
            ),
            "expect": "ON-SITE EXPERT",
            "inputs": {
                "facility": "Gas gathering station 7 (illustrative)",
                "assessor": "EAF assessment team",
                "eem_id": 54,
                "readiness": _evidence(_STATION_7_SCORES, _STATION_7_EXTRA),
                "hazard_vector": [1, 3, 1, 3, 3, 3],
                "data_sufficiency_D": 55,
                "action_complexity_C": 70,
                "verification_need_V": 90,
                "opportunity_scores": [80, 75, 70],
                "readiness_weight_mode": "bounded",
                "criticality_weight_mode": "equal",
                "flags": _conditions(
                    direct_verification_required=True,
                    digital_evidence_validated=True,
                    internal_capability_adequate=True,
                    protocol_requirements_satisfied=True,
                ),
                "rationale": (
                    "Leak quantification, packing condition and vibration evidence "
                    "require measurement at the machine."
                ),
            },
        },
    ],
    "provenance": (
        "Hazard ratings, D = 55, C = 70, V = 90 and the benefit scores "
        "z = (80, 75, 70) are all stated for EEM 54 in Section 5.2. The evidence item "
        "scores are illustrative and were chosen so that Equation (4) reproduces the "
        "Section 5.1 readiness vector."
    ),
}


CASE_STUDIES = [_CASE_1, _CASE_2, _CASE_3]


def index() -> list[dict]:
    """Case studies without their input payloads, for the picker."""
    return [
        {
            key: value
            for key, value in case.items()
            if key != "runs"
        }
        | {
            "runs": [
                {
                    "run_key": run["run_key"],
                    "label": run["label"],
                    "note": run["note"],
                    "expect": run["expect"],
                }
                for run in case["runs"]
            ]
        }
        for case in CASE_STUDIES
    ]


def find_run(case_id: str, run_key: str) -> Optional[tuple[dict, dict]]:
    for case in CASE_STUDIES:
        if case["case_id"] != case_id:
            continue
        for run in case["runs"]:
            if run["run_key"] == run_key:
                return case, run
    return None
