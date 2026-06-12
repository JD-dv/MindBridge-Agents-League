from __future__ import annotations

import unittest

from workwell_agent import (
    SYNTHETIC_TEAM,
    RiskLevel,
    WorkSignals,
    assess_signals,
    assess_team,
    build_bridge_request,
)


class WorkWellScoringTests(unittest.TestCase):
    def test_normal_upper_boundary(self):
        result = assess_signals(WorkSignals(1, 10, 1.0, 1))
        self.assertEqual(result.score, 2)
        self.assertEqual(result.level, RiskLevel.NORMAL)

    def test_early_warning_boundaries(self):
        lower = assess_signals(WorkSignals(1, 15, 1.0, 1))
        upper = assess_signals(WorkSignals(2, 30, 1.0, 1))
        self.assertEqual((lower.score, lower.level), (3, RiskLevel.EARLY_WARNING))
        self.assertEqual((upper.score, upper.level), (5, RiskLevel.EARLY_WARNING))

    def test_moderate_boundaries(self):
        lower = assess_signals(WorkSignals(2, 30, 1.5, 1))
        upper = assess_signals(WorkSignals(3, 30, 2.0, 1))
        self.assertEqual((lower.score, lower.level), (6, RiskLevel.MODERATE))
        self.assertEqual((upper.score, upper.level), (8, RiskLevel.MODERATE))

    def test_escalation_boundary(self):
        result = assess_signals(WorkSignals(3, 30, 2.0, 2))
        self.assertEqual(result.score, 9)
        self.assertEqual(result.level, RiskLevel.ESCALATE)
        self.assertTrue(result.should_escalate)

    def test_values_are_safely_bounded(self):
        result = assess_signals(WorkSignals(99, 999, 99, 99))
        self.assertEqual(result.score, 13)
        self.assertEqual(result.level, RiskLevel.ESCALATE)


class WorkWellCoachingTests(unittest.TestCase):
    def test_manager_coaching_avoids_diagnostic_language(self):
        forbidden = ("diagnos", "depress", "disorder", "mentally ill")
        for signals in (
            WorkSignals(0, 0, 1.0, 0),
            WorkSignals(1, 15, 1.0, 1),
            WorkSignals(2, 30, 1.5, 1),
            WorkSignals(3, 30, 2.0, 2),
        ):
            assessment = assess_signals(signals)
            text = (
                assessment.manager_nudge + " " + assessment.conversation_starter
            ).casefold()
            for term in forbidden:
                self.assertNotIn(term, text)

    def test_evidence_contains_only_observed_signal_summary(self):
        result = assess_signals(WorkSignals(2, 40, 2.5, 2))
        self.assertIn("2 missed check-in(s)", result.evidence)
        self.assertIn("Meeting participation down 40%", result.evidence)
        self.assertIn("Response time is 2.5x the usual pattern", result.evidence)


class TeamOverviewTests(unittest.TestCase):
    def setUp(self):
        self.overview = assess_team()

    def test_team_contains_six_first_name_only_profiles(self):
        self.assertEqual(len(SYNTHETIC_TEAM), 6)
        self.assertEqual(
            [employee.first_name for employee in SYNTHETIC_TEAM],
            ["Ari", "Ben", "Cal", "Dev", "Eli", "Finn"],
        )
        for employee in SYNTHETIC_TEAM:
            self.assertNotIn(" ", employee.first_name)
            self.assertNotIn("@", employee.first_name)
            self.assertNotIn("@", employee.role)

    def test_profiles_have_intended_support_levels(self):
        levels = {
            member.employee.first_name: member.assessment.level
            for member in self.overview.members
        }
        self.assertEqual(levels["Ari"], RiskLevel.NORMAL)
        self.assertEqual(levels["Ben"], RiskLevel.EARLY_WARNING)
        self.assertEqual(levels["Cal"], RiskLevel.MODERATE)
        self.assertEqual(levels["Dev"], RiskLevel.ESCALATE)
        self.assertEqual(levels["Eli"], RiskLevel.NORMAL)
        self.assertEqual(levels["Finn"], RiskLevel.MODERATE)

    def test_each_display_row_has_required_fields(self):
        for member in self.overview.members:
            self.assertTrue(member.employee.first_name)
            self.assertTrue(member.employee.role)
            self.assertTrue(member.signal_summary)
            self.assertIsInstance(member.assessment.level, RiskLevel)
            self.assertTrue(member.suggested_action)

    def test_aggregate_metrics_and_counts(self):
        self.assertEqual(self.overview.total_missed_check_ins, 9)
        self.assertAlmostEqual(self.overview.average_participation_drop, 27.5)
        self.assertAlmostEqual(self.overview.average_response_delay, 1.916666, places=5)
        self.assertEqual(self.overview.level_counts[RiskLevel.NORMAL], 2)
        self.assertEqual(self.overview.level_counts[RiskLevel.EARLY_WARNING], 1)
        self.assertEqual(self.overview.level_counts[RiskLevel.MODERATE], 2)
        self.assertEqual(self.overview.level_counts[RiskLevel.ESCALATE], 1)

    def test_suggested_check_ins_are_grouped_and_exclude_normal(self):
        suggestions = [
            (member.employee.first_name, member.assessment.level)
            for member in self.overview.suggested_check_ins
        ]
        self.assertEqual(
            suggestions,
            [
                ("Dev", RiskLevel.ESCALATE),
                ("Cal", RiskLevel.MODERATE),
                ("Finn", RiskLevel.MODERATE),
                ("Ben", RiskLevel.EARLY_WARNING),
            ],
        )
        self.assertNotIn("Ari", [name for name, _level in suggestions])
        self.assertNotIn("Eli", [name for name, _level in suggestions])

    def test_team_copy_contains_no_diagnostic_or_ranking_language(self):
        flattened = " ".join(
            " ".join(
                (
                member.signal_summary,
                member.suggested_action,
                member.assessment.conversation_starter,
                )
            )
            for member in self.overview.members
        ).casefold()
        for forbidden in (
            "diagnosis",
            "suicide-risk ranking",
            "mental-health score",
            "suspected disorder",
            "mentally ill",
        ):
            self.assertNotIn(forbidden, flattened)

    def test_empty_team_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            assess_team(())


class BridgeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.escalation = assess_signals(WorkSignals(3, 30, 2.0, 2))

    def test_escalation_builds_minimal_bridge_request(self):
        request = build_bridge_request(
            self.escalation,
            country=" Philippines ",
            language=" Filipino ",
            concern=" Employee says he cannot cope. ",
        )
        self.assertEqual(request.country, "Philippines")
        self.assertEqual(request.language, "Filipino")
        self.assertEqual(request.situation, "Employee says he cannot cope.")
        self.assertNotIn("missed", request.situation)
        self.assertNotIn("participation", request.situation)

    def test_empty_concern_uses_safe_handoff_summary(self):
        request = build_bridge_request(
            self.escalation,
            country="UK",
            language="",
            concern="",
        )
        self.assertEqual(request.language, "English")
        self.assertIn("mental health support", request.situation)

    def test_non_escalation_cannot_build_handoff(self):
        moderate = assess_signals(WorkSignals(2, 30, 1.5, 1))
        with self.assertRaisesRegex(ValueError, "escalation-level"):
            build_bridge_request(
                moderate,
                country="US",
                language="English",
                concern="Concern",
            )


if __name__ == "__main__":
    unittest.main()
