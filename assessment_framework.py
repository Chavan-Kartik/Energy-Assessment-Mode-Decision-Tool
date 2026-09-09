"""
Risk-Informed, Readiness-Aware Energy Assessment Framework
Reference Python implementation of Algorithm 1 from the manuscript.

Purpose
-------
This module operationalizes the manuscript's computational sequence:
1. Validate inputs and mandatory evidence.
2. Compute the readiness vector S and non-compensatory gate G.
3. Compute robust Readiness Index (RI) envelopes over admissible weights.
4. Compute CRIS and normalized interaction intensity R.
5. Compute Opportunity Priority (OP) envelopes and pairwise rank stability.
6. Compute Assessment Criticality (AC) envelopes.
7. Apply the Phase-1 readiness gate; if it fails, return READINESS IMPROVEMENT / HOLD.
8. Apply EEM-specific safety/direct-verification overrides.
9. Select SELF, REMOTE SPECIALIST, or ON-SITE EXPERT assessment.
10. Return an auditable decision record.

Important
---------
This is a research/reference implementation for screening and assessment
planning. It does NOT replace PHA, HAZOP, quantitative risk assessment,
management of change (MOC), code compliance, detailed engineering, or
operator-specific safety approval.

Dependencies
------------
numpy
scipy
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Any

import numpy as np
from scipy.optimize import linprog


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

READINESS_DIMENSIONS = (
    "data_availability",
    "workforce_capability",
    "management_commitment",
    "baseline_status",
    "implementation_readiness",
)

HAZARD_DOMAINS = (
    "well_control",
    "fire_explosion",
    "electrical_hazard",
    "toxic_exposure",
    "mechanical_failure",
    "environmental_impact",
)


@dataclass
class EvidenceItem:
    """
    Evidence coding used by the readiness model.

    score:
        0 = absent / not demonstrated
        1 = partial, informal, outdated, or inconsistently applied
        2 = current, documented, accessible, and demonstrated
        None = not applicable (removed from denominator)

    mandatory:
        If True, the item participates in the non-compensatory gate G.

    threshold:
        Minimum acceptable evidence score for a mandatory item.
        Example: threshold=2 requires fully demonstrated evidence.
    """
    name: str
    score: Optional[int]
    mandatory: bool = False
    threshold: int = 1
    evidence_reference: Optional[str] = None


@dataclass
class PreferenceSet:
    """
    Linear admissible weight set.

    The score is linear in weights:
        score(w) = values @ w

    Constraints:
        lower_i <= w_i <= upper_i
        sum(w_i) = 1
        A_ub @ w <= b_ub
        A_eq @ w == b_eq

    If no custom constraints are provided, only the bounds and sum-to-one
    constraint are enforced.
    """
    lower: Sequence[float]
    upper: Sequence[float]
    A_ub: Optional[Sequence[Sequence[float]]] = None
    b_ub: Optional[Sequence[float]] = None
    A_eq: Optional[Sequence[Sequence[float]]] = None
    b_eq: Optional[Sequence[float]] = None
    label: str = "admissible_weight_set"


@dataclass
class EnvelopeResult:
    minimum: float
    maximum: float
    weights_at_minimum: List[float]
    weights_at_maximum: List[float]


@dataclass
class RankStabilityResult:
    min_difference: float
    max_difference: float
    necessary_a_over_b: bool
    possible_a_over_b: bool
    stable_ordering: bool
    interpretation: str


@dataclass
class DecisionInputs:
    """
    Inputs needed by the rule-based assessment-mode engine.
    """
    gate_passed: bool
    internal_capability_adequate: bool
    digital_evidence_validated: bool
    protocol_requirements_satisfied: bool
    specialist_interpretation_required: bool
    direct_verification_required: bool
    safety_override: bool
    unresolved_evidence_requires_field: bool = False
    reviewer_rationale: str = ""


@dataclass
class AssessmentRecord:
    assessment_id: str
    eem_id: str
    timestamp_utc: str
    readiness_vector: Dict[str, float]
    readiness_gate: bool
    readiness_interval: Optional[Tuple[float, float]]
    hazard_vector: Dict[str, int]
    cris: float
    normalized_interaction: float
    opportunity_interval: Optional[Tuple[float, float]]
    assessment_criticality_interval: Optional[Tuple[float, float]]
    selected_mode: str
    override_triggered: bool
    rationale: str
    next_actions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_0_100(name: str, value: float) -> None:
    if not (0.0 <= float(value) <= 100.0):
        raise ValueError(f"{name} must be in [0, 100]; got {value}.")


def validate_hazard_vector(hazard_vector: Sequence[int]) -> None:
    if len(hazard_vector) != 6:
        raise ValueError("Hazard vector must contain exactly 6 domain ratings.")
    for x in hazard_vector:
        if int(x) not in (0, 1, 2, 3):
            raise ValueError(
                "Each hazard rating must be 0=None, 1=Low, 2=Medium, or 3=High."
            )


def validate_preference_set(pref: PreferenceSet, n: int) -> None:
    if len(pref.lower) != n or len(pref.upper) != n:
        raise ValueError("Preference-set bounds must match the score-vector length.")
    for lo, hi in zip(pref.lower, pref.upper):
        if lo < 0 or hi < 0 or lo > hi:
            raise ValueError(f"Invalid weight bound ({lo}, {hi}).")


# ---------------------------------------------------------------------------
# Equation (4): readiness dimensions
# ---------------------------------------------------------------------------

def compute_readiness_vector(
    readiness_evidence: Dict[str, Sequence[EvidenceItem]]
) -> Dict[str, float]:
    """
    Computes S_i = 100 * sum(e_ik) / (2*n_i).

    Not-applicable items (score=None) are removed from n_i.
    At least one applicable evidence item must remain in every dimension.
    """
    result: Dict[str, float] = {}

    for dimension in READINESS_DIMENSIONS:
        if dimension not in readiness_evidence:
            raise ValueError(f"Missing readiness dimension: {dimension}")

        applicable = [
            item for item in readiness_evidence[dimension] if item.score is not None
        ]
        if not applicable:
            raise ValueError(
                f"Readiness dimension '{dimension}' has no applicable evidence items."
            )

        for item in applicable:
            if item.score not in (0, 1, 2):
                raise ValueError(
                    f"Evidence score for '{item.name}' must be 0, 1, 2, or None."
                )

        total = sum(int(item.score) for item in applicable)
        n_i = len(applicable)
        result[dimension] = 100.0 * total / (2.0 * n_i)

    return result


# ---------------------------------------------------------------------------
# Equation (7): non-compensatory evidence gate
# ---------------------------------------------------------------------------

def compute_readiness_gate(
    readiness_evidence: Dict[str, Sequence[EvidenceItem]]
) -> Tuple[bool, List[str]]:
    """
    G = 1 iff every mandatory evidence item meets its threshold.

    Returns
    -------
    gate_passed, failed_items
    """
    failed: List[str] = []

    for dimension, items in readiness_evidence.items():
        for item in items:
            if not item.mandatory:
                continue

            if item.score is None or item.score < item.threshold:
                failed.append(f"{dimension}: {item.name}")

    return len(failed) == 0, failed


# ---------------------------------------------------------------------------
# Equations (5)-(6), (8), (10): robust linear score envelopes
# ---------------------------------------------------------------------------

def linear_score_envelope(
    values: Sequence[float],
    pref: PreferenceSet,
) -> EnvelopeResult:
    """
    Computes exact min/max of a linear additive score over an admissible
    weight set using linear programming.
    """
    v = np.asarray(values, dtype=float)
    n = len(v)
    validate_preference_set(pref, n)

    bounds = list(zip(pref.lower, pref.upper))

    # Sum-to-one is always imposed.
    A_eq_parts = [np.ones(n)]
    b_eq_parts = [1.0]

    if pref.A_eq is not None:
        custom_A_eq = np.asarray(pref.A_eq, dtype=float)
        if custom_A_eq.ndim == 1:
            custom_A_eq = custom_A_eq.reshape(1, -1)
        A_eq_parts.extend(list(custom_A_eq))
        b_eq_parts.extend(list(np.asarray(pref.b_eq, dtype=float)))

    A_eq = np.asarray(A_eq_parts, dtype=float)
    b_eq = np.asarray(b_eq_parts, dtype=float)

    A_ub = None
    b_ub = None
    if pref.A_ub is not None:
        A_ub = np.asarray(pref.A_ub, dtype=float)
        if A_ub.ndim == 1:
            A_ub = A_ub.reshape(1, -1)
        b_ub = np.asarray(pref.b_ub, dtype=float)

    res_min = linprog(
        c=v,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not res_min.success:
        raise ValueError(
            f"Infeasible/invalid preference set for minimum: {res_min.message}"
        )

    res_max = linprog(
        c=-v,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not res_max.success:
        raise ValueError(
            f"Infeasible/invalid preference set for maximum: {res_max.message}"
        )

    return EnvelopeResult(
        minimum=float(res_min.fun),
        maximum=float(-res_max.fun),
        weights_at_minimum=res_min.x.tolist(),
        weights_at_maximum=res_max.x.tolist(),
    )


def reference_weighted_score(
    values: Sequence[float],
    weights: Sequence[float],
) -> float:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    if len(v) != len(w):
        raise ValueError("Values and weights must have the same length.")
    if np.any(w < 0):
        raise ValueError("Weights must be nonnegative.")
    if not np.isclose(w.sum(), 1.0):
        raise ValueError("Weights must sum to 1.")
    return float(v @ w)


# ---------------------------------------------------------------------------
# Equations (1)-(3): hazard vector, CRIS, normalized interaction
# ---------------------------------------------------------------------------

def compute_cris(hazard_vector: Sequence[int]) -> Tuple[float, float]:
    """
    CRIS_j = sum_k x_jk, 0 <= CRIS <= 18
    R_j    = 100 * CRIS_j / (3*K), K=6
    """
    validate_hazard_vector(hazard_vector)
    cris = float(sum(hazard_vector))
    K = 6
    normalized = 100.0 * cris / (3.0 * K)
    return cris, normalized


def hazard_vector_dict(hazard_vector: Sequence[int]) -> Dict[str, int]:
    validate_hazard_vector(hazard_vector)
    return dict(zip(HAZARD_DOMAINS, map(int, hazard_vector)))


# ---------------------------------------------------------------------------
# Equation (8): Opportunity Priority
# ---------------------------------------------------------------------------

def compute_opportunity_envelope(
    opportunity_scores: Sequence[float],
    preference_set_A: PreferenceSet,
) -> EnvelopeResult:
    for i, value in enumerate(opportunity_scores):
        _validate_0_100(f"opportunity_scores[{i}]", value)
    return linear_score_envelope(opportunity_scores, preference_set_A)


# ---------------------------------------------------------------------------
# Equations (9)-(10): Assessment Criticality
# ---------------------------------------------------------------------------

def compute_assessment_criticality_envelope(
    normalized_interaction_R: float,
    data_sufficiency_D: float,
    action_complexity_C: float,
    verification_need_V: float,
    preference_set_Q: PreferenceSet,
) -> EnvelopeResult:
    """
    AC_j(q) =
        q_R * R_j
        + q_D * (100 - D_j)
        + q_C * C_j
        + q_V * V_j
    """
    for name, value in (
        ("normalized_interaction_R", normalized_interaction_R),
        ("data_sufficiency_D", data_sufficiency_D),
        ("action_complexity_C", action_complexity_C),
        ("verification_need_V", verification_need_V),
    ):
        _validate_0_100(name, value)

    components = [
        normalized_interaction_R,
        100.0 - data_sufficiency_D,
        action_complexity_C,
        verification_need_V,
    ]
    return linear_score_envelope(components, preference_set_Q)


# ---------------------------------------------------------------------------
# Equations (11)-(12): necessary / possible preference
# ---------------------------------------------------------------------------

def pairwise_rank_stability(
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    preference_set: PreferenceSet,
    tolerance: float = 1e-9,
) -> RankStabilityResult:
    """
    For additive score vectors z_a and z_b:

    Necessary a >= b iff min_w [score_a(w)-score_b(w)] >= 0.
    Possible  a >= b iff max_w [score_a(w)-score_b(w)] >= 0.

    A stable strict ordering exists when the entire difference interval lies
    on one side of zero.
    """
    a = np.asarray(scores_a, dtype=float)
    b = np.asarray(scores_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("Pairwise score vectors must have identical shape.")

    diff = a - b
    env = linear_score_envelope(diff, preference_set)

    necessary = env.minimum >= -tolerance
    possible = env.maximum >= -tolerance

    if env.minimum > tolerance:
        stable = True
        interpretation = "A outranks B for every admissible weighting."
    elif env.maximum < -tolerance:
        stable = True
        interpretation = "B outranks A for every admissible weighting."
    else:
        stable = False
        interpretation = (
            "Ordering is preference-dependent; the admissible weight set "
            "contains weightings supporting both orderings or a tie."
        )

    return RankStabilityResult(
        min_difference=env.minimum,
        max_difference=env.maximum,
        necessary_a_over_b=necessary,
        possible_a_over_b=possible,
        stable_ordering=stable,
        interpretation=interpretation,
    )


# ---------------------------------------------------------------------------
# Algorithm 1, Steps 6-9: assessment-mode decision engine
# ---------------------------------------------------------------------------

def select_assessment_mode(inputs: DecisionInputs) -> Tuple[str, bool, str, List[str]]:
    """
    Implements the two-phase, non-compensatory decision sequence.

    Phase 1 disposition:
    1. If the facility-level mandatory readiness/evidence gate fails (G=0),
       return READINESS IMPROVEMENT / HOLD. This is a pre-assessment
       disposition, not one of the three assessment modes.

    Phase 2 assessment-mode selection (only after G=1):
    2. Safety override or required direct field verification -> ON-SITE EXPERT.
    3. Validated digital evidence + specialist interpretation -> REMOTE SPECIALIST.
    4. Adequate internal capability + validated evidence + protocol satisfied
       -> SELF-ASSESSMENT.
    5. Otherwise escalate according to the unresolved evidence requirement.
    """

    next_actions: List[str] = []

    # Phase 1: facility-level readiness/evidence gate
    if not inputs.gate_passed:
        rationale = (
            "READINESS IMPROVEMENT / HOLD selected because one or more mandatory "
            "facility-level readiness/evidence prerequisites are not satisfied. "
            "The EEM-specific assessment-mode decision is deferred until those "
            "prerequisites are resolved or the assessment scope is redefined."
        )
        next_actions.append("Resolve/document failed mandatory readiness/evidence items.")
        if inputs.reviewer_rationale:
            rationale += " Reviewer note: " + inputs.reviewer_rationale
        return "READINESS IMPROVEMENT / HOLD", True, rationale, next_actions

    # Phase 2 hard rules: EEM-specific safety/direct-verification override
    if inputs.direct_verification_required or inputs.safety_override:
        reasons = []
        if inputs.direct_verification_required:
            reasons.append("direct field verification is required")
            next_actions.append("Plan field measurement/inspection and engineering verification.")
        if inputs.safety_override:
            reasons.append("safety override triggered")
            next_actions.append("Interface with applicable MOC/PHA/HAZOP/engineering approval.")

        rationale = "ON-SITE EXPERT selected because " + "; ".join(reasons) + "."
        if inputs.reviewer_rationale:
            rationale += " Reviewer note: " + inputs.reviewer_rationale
        return "ON-SITE EXPERT", True, rationale, next_actions

    # Remote specialist route
    if inputs.digital_evidence_validated and inputs.specialist_interpretation_required:
        rationale = (
            "REMOTE SPECIALIST selected because the readiness gate is passed, "
            "validated digital evidence is available, specialist interpretation is "
            "required, and direct field verification is not essential."
        )
        next_actions.append("Prepare validated data package and remote evidence set.")
        if inputs.reviewer_rationale:
            rationale += " Reviewer note: " + inputs.reviewer_rationale
        return "REMOTE SPECIALIST", False, rationale, next_actions

    # Self-assessment route
    if (
        inputs.internal_capability_adequate
        and inputs.protocol_requirements_satisfied
        and inputs.digital_evidence_validated
        and not inputs.specialist_interpretation_required
    ):
        rationale = (
            "SELF-ASSESSMENT selected because the readiness gate is passed, internal "
            "capability is adequate, validated evidence is available, protocol "
            "requirements are satisfied, and no specialist/direct-field override is present."
        )
        next_actions.append("Execute internal assessment protocol and document evidence.")
        if inputs.reviewer_rationale:
            rationale += " Reviewer note: " + inputs.reviewer_rationale
        return "SELF-ASSESSMENT", False, rationale, next_actions

    # Unresolved / escalation
    if inputs.unresolved_evidence_requires_field:
        rationale = (
            "ON-SITE EXPERT selected by escalation because unresolved EEM-specific "
            "evidence requires field observation, measurement, or engineering judgment."
        )
        next_actions.append("Define unresolved evidence and field-verification plan.")
        if inputs.reviewer_rationale:
            rationale += " Reviewer note: " + inputs.reviewer_rationale
        return "ON-SITE EXPERT", False, rationale, next_actions

    rationale = (
        "REMOTE SPECIALIST selected by escalation because the case does not satisfy "
        "the self-assessment conditions, while the unresolved requirement has not "
        "been identified as requiring direct field verification."
    )
    next_actions.append("Obtain specialist review and close remaining evidence gaps.")
    if inputs.reviewer_rationale:
        rationale += " Reviewer note: " + inputs.reviewer_rationale
    return "REMOTE SPECIALIST", False, rationale, next_actions


# ---------------------------------------------------------------------------
# Full Algorithm 1 wrapper
# ---------------------------------------------------------------------------

def run_assessment_algorithm(
    *,
    assessment_id: str,
    eem_id: str,
    readiness_evidence: Dict[str, Sequence[EvidenceItem]],
    hazard_vector: Sequence[int],
    readiness_preference_W: Optional[PreferenceSet],
    opportunity_scores: Optional[Sequence[float]],
    opportunity_preference_A: Optional[PreferenceSet],
    data_sufficiency_D: float,
    action_complexity_C: float,
    verification_need_V: float,
    criticality_preference_Q: PreferenceSet,
    decision_inputs_without_gate: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> AssessmentRecord:
    """
    Runs the complete manuscript Algorithm 1 for a single EEM.

    The caller supplies facility-specific benefit/opportunity values if they exist.
    If opportunity_scores is None, no OP interval is reported.
    """

    # Step 1: validation is performed throughout the helper functions.

    # Step 2: readiness vector, gate, and optional RI envelope
    S_dict = compute_readiness_vector(readiness_evidence)
    gate_passed, failed_items = compute_readiness_gate(readiness_evidence)
    S = [S_dict[d] for d in READINESS_DIMENSIONS]

    ri_env: Optional[EnvelopeResult] = None
    if readiness_preference_W is not None:
        ri_env = linear_score_envelope(S, readiness_preference_W)

    # Step 3: CRIS and normalized interaction
    cris, R = compute_cris(hazard_vector)

    # Step 4: Opportunity Priority, where facility-specific inputs exist
    op_env: Optional[EnvelopeResult] = None
    if opportunity_scores is not None:
        if opportunity_preference_A is None:
            raise ValueError(
                "opportunity_preference_A is required when opportunity_scores are supplied."
            )
        op_env = compute_opportunity_envelope(
            opportunity_scores,
            opportunity_preference_A,
        )

    # Step 5: Assessment Criticality
    ac_env = compute_assessment_criticality_envelope(
        normalized_interaction_R=R,
        data_sufficiency_D=data_sufficiency_D,
        action_complexity_C=action_complexity_C,
        verification_need_V=verification_need_V,
        preference_set_Q=criticality_preference_Q,
    )

    # Steps 6-9: decision mode
    decision_inputs = DecisionInputs(
        gate_passed=gate_passed,
        **decision_inputs_without_gate,
    )
    mode, override_triggered, rationale, next_actions = select_assessment_mode(
        decision_inputs
    )

    if failed_items:
        next_actions.append("Failed mandatory evidence: " + "; ".join(failed_items))

    # Step 10: audit record
    return AssessmentRecord(
        assessment_id=assessment_id,
        eem_id=eem_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        readiness_vector=S_dict,
        readiness_gate=gate_passed,
        readiness_interval=(
            (ri_env.minimum, ri_env.maximum) if ri_env is not None else None
        ),
        hazard_vector=hazard_vector_dict(hazard_vector),
        cris=cris,
        normalized_interaction=R,
        opportunity_interval=(
            (op_env.minimum, op_env.maximum) if op_env is not None else None
        ),
        assessment_criticality_interval=(ac_env.minimum, ac_env.maximum),
        selected_mode=mode,
        override_triggered=override_triggered,
        rationale=rationale,
        next_actions=next_actions,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Example reproducing the manuscript's illustrative calculations
# ---------------------------------------------------------------------------

def manuscript_example() -> AssessmentRecord:
    """
    Demonstration only. These are illustrative values from the manuscript,
    not field-calibrated thresholds or observed facility data.
    """

    # Construct simple evidence lists that reproduce:
    # S = (80, 70, 75, 60, 65)
    #
    # Using 10 checklist items per dimension gives exact 5-point increments
    # with the 0/1/2 evidence coding.
    def evidence_for_target(name: str, target: int) -> List[EvidenceItem]:
        # 10 items => denominator = 20 evidence points.
        needed_points = int(round(target / 5))
        scores = [2] * (needed_points // 2)
        if needed_points % 2:
            scores.append(1)
        scores += [0] * (10 - len(scores))
        return [
            EvidenceItem(
                name=f"{name}_{i+1}",
                score=s,
                mandatory=(i == 0),
                threshold=1,
            )
            for i, s in enumerate(scores)
        ]

    readiness_evidence = {
        "data_availability": evidence_for_target("data", 80),
        "workforce_capability": evidence_for_target("workforce", 70),
        "management_commitment": evidence_for_target("management", 75),
        "baseline_status": evidence_for_target("baseline", 60),
        "implementation_readiness": evidence_for_target("implementation", 65),
    }

    # Manuscript example: 0.10 <= w_i <= 0.35
    W = PreferenceSet(
        lower=[0.10] * 5,
        upper=[0.35] * 5,
        label="RI illustrative bounds",
    )

    # Example neutral opportunity model with three benefit dimensions.
    A = PreferenceSet(
        lower=[1 / 3] * 3,
        upper=[1 / 3] * 3,
        label="equal opportunity weights",
    )

    # Equal AC weights for the manuscript's example.
    Q = PreferenceSet(
        lower=[0.25] * 4,
        upper=[0.25] * 4,
        label="equal criticality weights",
    )

    # EEM 54 example: CRIS = 14.
    # One hazard vector consistent with the manuscript's Appendix B:
    # WC=L(1), FE=H(3), EH=L(1), TE=H(3), MF=H(3), EI=H(3)
    hazard_vector = [1, 3, 1, 3, 3, 3]

    record = run_assessment_algorithm(
        assessment_id="EXAMPLE-001",
        eem_id="EEM-54",
        readiness_evidence=readiness_evidence,
        hazard_vector=hazard_vector,
        readiness_preference_W=W,
        opportunity_scores=[80, 75, 70],
        opportunity_preference_A=A,
        data_sufficiency_D=55,
        action_complexity_C=70,
        verification_need_V=90,
        criticality_preference_Q=Q,
        decision_inputs_without_gate={
            "internal_capability_adequate": True,
            "digital_evidence_validated": False,
            "protocol_requirements_satisfied": True,
            "specialist_interpretation_required": True,
            "direct_verification_required": True,
            "safety_override": False,
            "unresolved_evidence_requires_field": True,
            "reviewer_rationale": (
                "Leak quantification and compressor condition require field verification."
            ),
        },
        metadata={
            "framework_version": "reference-1.1",
            "note": "Illustrative manuscript example; not field-calibrated.",
        },
    )

    return record


if __name__ == "__main__":
    import json

    result = manuscript_example()
    print(json.dumps(asdict(result), indent=2))

    # Expected checks from the manuscript example:
    print("\nKey manuscript checks")
    print("---------------------")
    print("Readiness interval should be approximately [66.25, 73.75]:",
          result.readiness_interval)
    print("CRIS should be 14:", result.cris)
    print("Normalized interaction R should be approximately 77.78:",
          round(result.normalized_interaction, 2))
    print("Equal-weight AC should be approximately 70.69:",
          result.assessment_criticality_interval)
    print("Selected mode:", result.selected_mode)