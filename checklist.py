"""
The input vocabulary the manuscript defines: readiness evidence items, hazard
domains, verification conditions, and the ordered mode-selection rules.

Nothing here calculates anything. These are the definitions the form is built
from and the labels used to describe a decision after assessment_framework.py has
made it. Keeping them on the server means the form, the stored case studies, and
the explanation of a result all read from the same list.

Section 4.5 requires the assessment team to define its own evidence item set and
its own mandatory subset, so these lists are defaults the user can edit, not a
fixed schema.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

# ---------------------------------------------------------------------------
# Appendix C, Table C1: readiness evidence
# ---------------------------------------------------------------------------
# Items marked mandatory are the four examples named in Section 4.5. The paper
# states that each mandatory item carries an acceptance criterion but does not
# prescribe its value, so the threshold below is a default for the user to set.

READINESS_CHECKLIST: list[dict] = [
    {
        "key": "data_availability",
        "symbol": "S\u2081",
        "title": "Data availability",
        "question": "Can the assessor obtain reliable operating and energy data?",
        "adaptation": (
            "Large integrated or offshore operators may rely on DCS/SCADA historians. "
            "Smaller onshore operators may use utility bills, engine-hour logs, tank "
            "tickets and manual production sheets. The evidence requirement is "
            "reliability and traceability, not a particular digital platform."
        ),
        "evidence_source": (
            "Meter lists; electricity and fuel bills; historian tags; flow, pressure and "
            "temperature trends; run hours; production records; calibration certificates; "
            "missing-data logs; demonstration of data extraction."
        ),
        "items": [
            ("Minimum process and energy data for the calculation", True),
            ("Meter list", False),
            ("Electricity and fuel bills", False),
            ("Historian tags", False),
            ("Flow, pressure and temperature trends", False),
            ("Run hours", False),
            ("Production records", False),
            ("Calibration certificates", False),
            ("Missing-data logs", False),
            ("Demonstration of data extraction", False),
        ],
    },
    {
        "key": "workforce_capability",
        "symbol": "S\u2082",
        "title": "Workforce capability",
        "question": "Can the site's people collect, understand and use the required information?",
        "adaptation": (
            "A major operator may demonstrate formal competency systems and specialist "
            "engineers. A smaller company can demonstrate equivalent capability through "
            "experienced multi-skilled personnel, contractor support and documented "
            "procedures."
        ),
        "evidence_source": (
            "Interviews with operations, maintenance and engineering staff; training "
            "records; competency matrices; examples of previous energy or reliability "
            "studies; ability to explain equipment operating envelopes and abnormal "
            "conditions."
        ),
        "items": [
            ("Required engineering competence for this scope", True),
            ("Interviews with operations and engineering staff", False),
            ("Training records", False),
            ("Competency matrices", False),
            ("Previous energy or reliability studies", False),
            ("Can explain operating envelopes and upsets", False),
        ],
    },
    {
        "key": "management_commitment",
        "symbol": "S\u2083",
        "title": "Management commitment",
        "question": "Is there visible authority and ownership to support the assessment?",
        "adaptation": (
            "Corporate companies may use formal governance and annual targets. Smaller "
            "firms may show commitment through owner or director approval, documented "
            "decisions, rapid budget authorization and clear responsibility."
        ),
        "evidence_source": (
            "Named sponsor; approved assessment scope; access authorization; meeting "
            "minutes; energy or operating objectives; budget route; management review "
            "records; evidence that previous recommendations were considered and closed."
        ),
        "items": [
            ("Safe access authorization", True),
            ("Named sponsor", False),
            ("Approved assessment scope", False),
            ("Meeting minutes", False),
            ("Energy or operating objectives", False),
            ("Budget route", False),
            ("Management review records", False),
            ("Previous recommendations closed out", False),
        ],
    },
    {
        "key": "baseline_status",
        "symbol": "S\u2084",
        "title": "Baseline status",
        "question": "Is there a credible reference against which improvement can be measured?",
        "adaptation": (
            "Continuous-process facilities may use normalized energy intensity. Drilling "
            "contractors may use fuel per operating hour or activity phase. Artificial-lift "
            "operations may use energy per unit fluid or oil produced. The metric changes, "
            "but the requirement for a reproducible reference does not."
        ),
        "evidence_source": (
            "Defined assessment boundary; historical energy and production data; "
            "normalized KPIs; operating-mode records; weather or throughput normalization "
            "where relevant; documented baseline period; explanation of major changes."
        ),
        "items": [
            ("Definable assessment boundary", True),
            ("Historical energy and production data", False),
            ("Normalized KPIs", False),
            ("Operating-mode records", False),
            ("Weather or throughput normalization, where relevant", False),
            ("Documented baseline period", False),
            ("Explanation of major changes", False),
        ],
    },
    {
        "key": "implementation_readiness",
        "symbol": "S\u2085",
        "title": "Implementation readiness",
        "question": "Can an accepted recommendation actually be executed and verified?",
        "adaptation": (
            "Large operators may use formal capital-gate and MOC systems. Smaller operators "
            "may use maintenance planning and direct management approval. Readiness is "
            "demonstrated when responsibility, resources, timing and verification are "
            "identifiable."
        ),
        "evidence_source": (
            "Named action owner; maintenance or work-order route; procurement path; budget "
            "mechanism; shutdown or turnaround window; MOC or permit requirements; "
            "contractor availability; schedule; measurement and verification plan."
        ),
        "items": [
            ("Named action owner", False),
            ("Maintenance or work-order route", False),
            ("Procurement path", False),
            ("Budget mechanism", False),
            ("Shutdown or turnaround window", False),
            ("MOC or permit requirements", False),
            ("Contractor availability", False),
            ("Schedule", False),
            ("Measurement and verification plan", False),
        ],
    },
]

DEFAULT_THRESHOLD = 2


def default_evidence() -> dict[str, list[dict]]:
    """The checklist as an unscored form payload."""
    return {
        dimension["key"]: [
            {
                "name": name,
                "score": 0,
                "mandatory": mandatory,
                "threshold": DEFAULT_THRESHOLD,
            }
            for name, mandatory in dimension["items"]
        ]
        for dimension in READINESS_CHECKLIST
    }


# ---------------------------------------------------------------------------
# Equation (1): the six interaction domains
# ---------------------------------------------------------------------------

HAZARD_DOMAINS: list[dict] = [
    {"key": "well_control", "abbr": "WC", "title": "Well control"},
    {"key": "fire_explosion", "abbr": "FE", "title": "Fire / explosion"},
    {"key": "electrical_hazard", "abbr": "EH", "title": "Electrical hazard"},
    {"key": "toxic_exposure", "abbr": "TE", "title": "Toxic exposure"},
    {"key": "mechanical_failure", "abbr": "MF", "title": "Mechanical failure"},
    {"key": "environmental_impact", "abbr": "EI", "title": "Environmental impact"},
]

HAZARD_LEVELS = ["None", "Low", "Medium", "High"]


# ---------------------------------------------------------------------------
# Table 4: the verification conditions the mode rules read
# ---------------------------------------------------------------------------

CONDITIONS: list[dict] = [
    {
        "key": "direct_verification_required",
        "short": "Direct verification required",
        "question": "Direct field observation or measurement is required",
        "note": "Non-compensatory: this alone selects on-site expert assessment.",
    },
    {
        "key": "safety_override",
        "short": "Safety override declared",
        "question": "A safety override has been declared for this measure",
        "note": "Non-compensatory: this alone selects on-site expert assessment.",
    },
    {
        "key": "digital_evidence_validated",
        "short": "Digital evidence validated",
        "question": "The available digital evidence is validated",
        "note": "",
    },
    {
        "key": "specialist_interpretation_required",
        "short": "Specialist interpretation required",
        "question": "Specialist interpretation is required",
        "note": "",
    },
    {
        "key": "internal_capability_adequate",
        "short": "Internal capability adequate",
        "question": "Internal engineering capability is adequate",
        "note": "",
    },
    {
        "key": "protocol_requirements_satisfied",
        "short": "Protocol requirements satisfied",
        "question": "Internal protocol requirements are satisfied",
        "note": "",
    },
    {
        "key": "unresolved_evidence_requires_field",
        "short": "Unresolved gap needs field work",
        "question": "Any unresolved evidence gap would need field work",
        "note": "Used only for escalation when the self-assessment conditions are not met.",
    },
]

CONDITION_KEYS = [condition["key"] for condition in CONDITIONS]


def default_conditions() -> dict[str, bool]:
    return {key: False for key in CONDITION_KEYS}


# ---------------------------------------------------------------------------
# Algorithm 1, steps 7-9: the ordered rules, restated for explanation
# ---------------------------------------------------------------------------
# These mirror select_assessment_mode() in assessment_framework.py so a result can
# be shown as the ladder it came from. They do not decide anything: app.py checks
# the rule it identifies against the mode the framework actually returned and
# refuses to display a trace that disagrees with it.


class Rule(NamedTuple):
    id: str
    phase: str
    mode: str
    label: str
    condition: str
    holds: Callable[[dict, bool], bool]


RULE_LADDER: list[Rule] = [
    Rule(
        id="phase1_gate",
        phase="Phase 1",
        mode="READINESS IMPROVEMENT / HOLD",
        label="Readiness gate",
        condition="G = 0, at least one mandatory evidence item is below its threshold",
        holds=lambda flags, gate: not gate,
    ),
    Rule(
        id="override",
        phase="Phase 2",
        mode="ON-SITE EXPERT",
        label="Safety / direct-verification override",
        condition="direct verification is required, or a safety override is declared",
        holds=lambda flags, gate: (
            flags["direct_verification_required"] or flags["safety_override"]
        ),
    ),
    Rule(
        id="remote",
        phase="Phase 2",
        mode="REMOTE SPECIALIST",
        label="Remote specialist route",
        condition="digital evidence is validated and specialist interpretation is required",
        holds=lambda flags, gate: (
            flags["digital_evidence_validated"]
            and flags["specialist_interpretation_required"]
        ),
    ),
    Rule(
        id="self",
        phase="Phase 2",
        mode="SELF-ASSESSMENT",
        label="Self-assessment route",
        condition=(
            "internal capability adequate, protocol satisfied, evidence validated, "
            "no specialist reading needed"
        ),
        holds=lambda flags, gate: (
            flags["internal_capability_adequate"]
            and flags["protocol_requirements_satisfied"]
            and flags["digital_evidence_validated"]
            and not flags["specialist_interpretation_required"]
        ),
    ),
    Rule(
        id="escalate_field",
        phase="Phase 2",
        mode="ON-SITE EXPERT",
        label="Escalation to field",
        condition="an unresolved evidence gap requires field observation or measurement",
        holds=lambda flags, gate: flags["unresolved_evidence_requires_field"],
    ),
    Rule(
        id="escalate_remote",
        phase="Phase 2",
        mode="REMOTE SPECIALIST",
        label="Escalation to specialist",
        condition="no earlier rule applies and no field work has been identified as necessary",
        holds=lambda flags, gate: True,
    ),
]
