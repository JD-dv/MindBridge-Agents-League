from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import SYNTHETIC_DATA_NOTICE, source_label
from bridge_agent import BridgeRecommendation


class DashboardTests(unittest.TestCase):
    def test_dashboard_starts_on_repeatable_crisis_demo(self):
        app = AppTest.from_file("app.py").run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.tabs], ["Team Overview", "Private Review"])
        self.assertEqual(app.selectbox[0].value, "Potential crisis")
        slider_values = {slider.label: slider.value for slider in app.slider}
        self.assertEqual(slider_values["Missed check-ins"], 4)
        self.assertEqual(slider_values["Meeting participation drop"], 65)
        self.assertEqual(slider_values["Response-time change"], 4.0)
        self.assertEqual(slider_values["Manager concern"], 3)

    def test_team_overview_shows_synthetic_people_and_required_notice(self):
        app = AppTest.from_file("app.py").run(timeout=20)
        page_text = " ".join(block.value for block in app.markdown)
        self.assertIn(
            "Synthetic team overview",
            [heading.value for heading in app.subheader],
        )
        self.assertIn(SYNTHETIC_DATA_NOTICE, app.info[0].value)
        for name in ("Ari", "Ben", "Cal", "Dev", "Eli", "Finn"):
            self.assertIn(name, page_text)
        self.assertIn("Work-pattern signals", page_text)
        self.assertIn("Suggested manager action", page_text)

    def test_team_overview_avoids_prohibited_framing(self):
        app = AppTest.from_file("app.py").run(timeout=20)
        page_text = " ".join(
            [block.value for block in app.markdown]
            + [item.value for item in app.caption]
        ).casefold()
        for forbidden in (
            "mental-health score",
            "suicide-risk ranking",
            "suspected disorder",
        ):
            self.assertNotIn(forbidden, page_text)

    def test_review_privately_preloads_signals_without_confirming_assessment(self):
        app = AppTest.from_file("app.py").run(timeout=20)
        review_button = next(
            button for button in app.button if button.key == "review_Dev"
        )
        review_button.click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertNotIn("assessment", app.session_state)
        self.assertNotIn("bridge_result", app.session_state)
        self.assertEqual(app.session_state["selected_employee_name"], "Dev")
        slider_values = {slider.label: slider.value for slider in app.slider}
        self.assertEqual(slider_values["Missed check-ins"], 4)
        self.assertEqual(slider_values["Meeting participation drop"], 65)
        self.assertEqual(slider_values["Response-time change"], 4.0)
        self.assertEqual(slider_values["Manager concern"], 3)
        self.assertFalse(
            any(
                button.label == "Send private Bridge handoff"
                for button in app.button
            )
        )

    def test_assessment_reveals_bridge_handoff(self):
        app = AppTest.from_file("app.py").run(timeout=20)
        form_button = next(
            button for button in app.button if button.label == "Run private assessment"
        )
        form_button.click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(
            any("Escalate" in block.value for block in app.markdown),
        )
        self.assertTrue(
            any(box.label == "Country" for box in app.selectbox),
        )
        self.assertTrue(
            any(
                button.label == "Send private Bridge handoff"
                for button in app.button
            ),
        )

    def test_source_labels_do_not_claim_fabric_is_connected(self):
        foundry_iq = BridgeRecommendation(
            message="Call 988.",
            severity="support",
            source="foundry_iq",
            escalated=True,
        )
        foundry = BridgeRecommendation(
            message="Call 988.",
            severity="support",
            source="foundry_agent",
            escalated=True,
        )
        fallback = BridgeRecommendation(
            message="Call 988.",
            severity="support",
            source="local_safety_fallback",
            escalated=True,
        )
        self.assertIn("Foundry IQ", source_label(foundry_iq))
        self.assertNotIn("Fabric", source_label(foundry_iq))
        self.assertIn("Foundry agent", source_label(foundry))
        self.assertEqual(source_label(fallback), "Local verified safety fallback")

    def test_readme_contains_required_synthetic_data_notice(self):
        readme = Path("README.md").read_text()
        self.assertIn(SYNTHETIC_DATA_NOTICE, readme)
        self.assertNotIn("@", readme)
        self.assertIn(
            "MindBridge uses Microsoft Foundry IQ as the Microsoft IQ layer",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
