"""Deterministic WorkWell assessment for the synthetic dashboard prototype."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import mean

from bridge_agent import BridgeRequest


class RiskLevel(str, Enum):
    NORMAL = "normal"
    EARLY_WARNING = "early_warning"
    MODERATE = "moderate"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class WorkSignals:
    missed_check_ins: int
    participation_drop: int
    response_delay: float
    manager_concern: int


@dataclass(frozen=True)
class WorkWellAssessment:
    score: int
    level: RiskLevel
    evidence: tuple[str, ...]
    manager_nudge: str
    conversation_starter: str

    @property
    def should_escalate(self) -> bool:
        return self.level is RiskLevel.ESCALATE


@dataclass(frozen=True)
class SyntheticEmployee:
    first_name: str
    role: str
    signals: WorkSignals


@dataclass(frozen=True)
class TeamMemberAssessment:
    employee: SyntheticEmployee
    assessment: WorkWellAssessment
    signal_summary: str
    suggested_action: str


@dataclass(frozen=True)
class TeamOverview:
    members: tuple[TeamMemberAssessment, ...]
    suggested_check_ins: tuple[TeamMemberAssessment, ...]
    total_missed_check_ins: int
    average_participation_drop: float
    average_response_delay: float
    level_counts: dict[RiskLevel, int]


SCENARIOS: dict[str, WorkSignals] = {
    "Steady week": WorkSignals(0, 5, 1.0, 0),
    "Early change": WorkSignals(1, 20, 1.6, 1),
    "Sustained disengagement": WorkSignals(2, 40, 2.5, 2),
    "Potential crisis": WorkSignals(4, 65, 4.0, 3),
}

SYNTHETIC_TEAM: tuple[SyntheticEmployee, ...] = (
    SyntheticEmployee(
        first_name="Ari",
        role="Product Designer",
        signals=WorkSignals(0, 5, 1.0, 0),
    ),
    SyntheticEmployee(
        first_name="Ben",
        role="Software Engineer",
        signals=WorkSignals(1, 20, 1.5, 1),
    ),
    SyntheticEmployee(
        first_name="Cal",
        role="Data Analyst",
        signals=WorkSignals(2, 35, 2.0, 1),
    ),
    SyntheticEmployee(
        first_name="Dev",
        role="Customer Specialist",
        signals=WorkSignals(4, 65, 4.0, 3),
    ),
    SyntheticEmployee(
        first_name="Eli",
        role="Operations Coordinator",
        signals=WorkSignals(1, 10, 1.0, 0),
    ),
    SyntheticEmployee(
        first_name="Finn",
        role="Marketing Associate",
        signals=WorkSignals(1, 30, 2.0, 1),
    ),
)


def _participation_points(drop: int) -> int:
    if drop >= 50:
        return 3
    if drop >= 30:
        return 2
    if drop >= 15:
        return 1
    return 0


def _response_points(delay: float) -> int:
    if delay >= 4:
        return 3
    if delay >= 2:
        return 2
    if delay >= 1.5:
        return 1
    return 0


def assess_signals(signals: WorkSignals) -> WorkWellAssessment:
    missed = min(max(signals.missed_check_ins, 0), 4)
    concern = min(max(signals.manager_concern, 0), 3)
    score = (
        missed
        + _participation_points(max(signals.participation_drop, 0))
        + _response_points(max(signals.response_delay, 1))
        + concern
    )

    if score >= 9:
        level = RiskLevel.ESCALATE
    elif score >= 6:
        level = RiskLevel.MODERATE
    elif score >= 3:
        level = RiskLevel.EARLY_WARNING
    else:
        level = RiskLevel.NORMAL

    evidence = _build_evidence(signals)
    nudge, starter = _coaching_for(level)
    return WorkWellAssessment(score, level, evidence, nudge, starter)


def _build_evidence(signals: WorkSignals) -> tuple[str, ...]:
    evidence = []
    if signals.missed_check_ins:
        evidence.append(f"{signals.missed_check_ins} missed check-in(s)")
    if signals.participation_drop >= 15:
        evidence.append(f"Meeting participation down {signals.participation_drop}%")
    if signals.response_delay >= 1.5:
        evidence.append(f"Response time is {signals.response_delay:.1f}x the usual pattern")
    if signals.manager_concern:
        evidence.append(f"Manager concern level {signals.manager_concern} of 3")
    return tuple(evidence) or ("No material change from the synthetic baseline",)


def _coaching_for(level: RiskLevel) -> tuple[str, str]:
    if level is RiskLevel.NORMAL:
        return (
            "No private intervention is suggested. Keep normal one-to-one routines.",
            "How has your workload felt this week?",
        )
    if level is RiskLevel.EARLY_WARNING:
        return (
            "A light, private check-in may help before the pattern becomes sustained.",
            "I noticed the week has looked a little different. How are things going?",
        )
    if level is RiskLevel.MODERATE:
        return (
            "Set aside a private conversation soon and focus on support, not performance.",
            "I wanted to check in privately. What would make work more manageable right now?",
        )
    return (
        "Pause performance discussion, check immediate safety privately, and prepare the Bridge handoff.",
        "I am concerned about you as a person. Are you safe right now, and can we connect you with support?",
    )


def summarize_signals(signals: WorkSignals) -> str:
    observations = []
    if signals.missed_check_ins:
        observations.append(f"{signals.missed_check_ins} missed check-in(s)")
    if signals.participation_drop >= 15:
        observations.append(f"participation down {signals.participation_drop}%")
    if signals.response_delay >= 1.5:
        observations.append(f"responses {signals.response_delay:.1f}x slower")
    if signals.manager_concern:
        observations.append(f"manager concern {signals.manager_concern}/3")
    return "; ".join(observations) or "No material change from synthetic baseline"


def assess_team(
    employees: tuple[SyntheticEmployee, ...] = SYNTHETIC_TEAM,
) -> TeamOverview:
    if not employees:
        raise ValueError("Team overview requires at least one synthetic employee.")

    members = []
    level_counts = {level: 0 for level in RiskLevel}
    for employee in employees:
        assessment = assess_signals(employee.signals)
        level_counts[assessment.level] += 1
        members.append(
            TeamMemberAssessment(
                employee=employee,
                assessment=assessment,
                signal_summary=summarize_signals(employee.signals),
                suggested_action=assessment.manager_nudge,
            )
        )

    suggested = tuple(
        member
        for level in (
            RiskLevel.ESCALATE,
            RiskLevel.MODERATE,
            RiskLevel.EARLY_WARNING,
        )
        for member in members
        if member.assessment.level is level
    )
    return TeamOverview(
        members=tuple(members),
        suggested_check_ins=suggested,
        total_missed_check_ins=sum(
            employee.signals.missed_check_ins for employee in employees
        ),
        average_participation_drop=mean(
            employee.signals.participation_drop for employee in employees
        ),
        average_response_delay=mean(
            employee.signals.response_delay for employee in employees
        ),
        level_counts=level_counts,
    )


def build_bridge_request(
    assessment: WorkWellAssessment,
    *,
    country: str,
    language: str,
    concern: str,
) -> BridgeRequest:
    if not assessment.should_escalate:
        raise ValueError("Bridge handoff is available only for escalation-level assessments.")
    situation = concern.strip() or (
        "A manager observed sustained workplace disengagement and is concerned "
        "the employee may need immediate mental health support."
    )
    return BridgeRequest(
        country=country.strip(),
        language=language.strip() or "English",
        situation=situation,
    )
