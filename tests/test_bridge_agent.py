from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceNotFoundError
from openai import BadRequestError
from httpx import Request, Response

import bridge_agent


class FakeResponses:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class SeedHelplineProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = bridge_agent.SeedHelplineProvider()

    def test_country_aliases_resolve_to_reviewed_records(self):
        cases = {
            "UK": ("GB", "116 123"),
            "England": ("GB", "116 123"),
            "USA": ("US", "988"),
            "United States of America": ("US", "988"),
            "PH": ("PH", "1553"),
            "Pilipinas": ("PH", "1553"),
            "Canada": ("CA", "988"),
            "Australia": ("AU", "13 11 14"),
        }
        for country, expected in cases.items():
            with self.subTest(country=country):
                record = self.provider.lookup(country)
                self.assertIsNotNone(record)
                self.assertEqual((record.country_code, record.number), expected)

    def test_unsupported_country_returns_none(self):
        self.assertIsNone(self.provider.lookup("France"))
        self.assertIsNone(self.provider.lookup(""))


class ConfigurationTests(unittest.TestCase):
    @patch("bridge_agent.load_dotenv")
    def test_missing_configuration_names_every_required_value(self, _load_dotenv):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME, AGENT_NAME",
            ):
                bridge_agent.load_settings()


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.provider = bridge_agent.SeedHelplineProvider()

    def test_immediate_danger_bypasses_model_and_uses_emergency_number(self):
        client = MagicMock()
        result = bridge_agent.get_recommendation(
            client,
            "MindBridge",
            "UK",
            "English",
            "I am about to kill myself",
            self.provider,
        )
        self.assertIn("999 or 112", result)
        self.assertIn("someone you trust", result)
        client.responses.create.assert_not_called()

    def test_unknown_country_immediate_danger_never_guesses_a_number(self):
        result = bridge_agent.immediate_danger_message("France", self.provider)
        self.assertIn("local emergency services", result)
        self.assertNotRegex(result, r"\b(988|911|999|112|1553)\b")

    def test_tool_result_for_unsupported_country_contains_no_number(self):
        result = json.loads(
            bridge_agent.lookup_tool_result(
                self.provider,
                json.dumps({"country": "France", "language": "French"}),
            )
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("number", result)

    def test_bridge_service_returns_immediate_danger_metadata(self):
        service = bridge_agent.BridgeService(
            MagicMock(),
            "MindBridge",
            self.provider,
        )
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="US",
                language="English",
                situation="I cannot stay safe and may kill myself.",
            )
        )
        self.assertEqual(result.severity, "immediate_danger")
        self.assertEqual(result.source, "local_safety_fallback")
        self.assertTrue(result.escalated)
        self.assertIn("911", result.message)


class FunctionCallLoopTests(unittest.TestCase):
    def setUp(self):
        self.provider = bridge_agent.SeedHelplineProvider()

    def test_function_call_is_executed_and_returned_to_agent(self):
        first = SimpleNamespace(
            id="response-1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    name=bridge_agent.LOOKUP_TOOL_NAME,
                    arguments=json.dumps(
                        {"country": "Philippines", "language": "English"}
                    ),
                    call_id="call-1",
                )
            ],
            output_text="",
        )
        final_text = (
            "Call 1553, the National Center for Mental Health Crisis Hotline. "
            "It is available 24/7 in the Philippines."
        )
        second = SimpleNamespace(id="response-2", output=[], output_text=final_text)
        client = SimpleNamespace(responses=FakeResponses([first, second]))

        result = bridge_agent.invoke_agent(
            client,
            "MindBridge",
            "Philippines",
            "English",
            "I feel overwhelmed and need someone to talk to.",
            self.provider,
        )

        self.assertEqual(result, final_text)
        self.assertEqual(len(client.responses.calls), 2)
        follow_up = client.responses.calls[1]
        self.assertEqual(follow_up["previous_response_id"], "response-1")
        self.assertEqual(follow_up["input"][0]["type"], "function_call_output")
        tool_payload = json.loads(follow_up["input"][0]["output"])
        self.assertEqual(tool_payload["record"]["number"], "1553")
        self.assertEqual(
            follow_up["extra_body"]["agent_reference"]["name"],
            "MindBridge",
        )

    def test_malformed_tool_arguments_raise_clear_error(self):
        with self.assertRaisesRegex(ValueError, "malformed lookup arguments"):
            bridge_agent.lookup_tool_result(self.provider, "{not-json")

    def test_empty_agent_response_uses_verified_fallback(self):
        response = SimpleNamespace(id="response-1", output=[], output_text=" ")
        client = SimpleNamespace(responses=FakeResponses([response]))
        result = bridge_agent.invoke_agent(
            client,
            "MindBridge",
            "US",
            "English",
            "I feel burned out.",
            self.provider,
        )
        self.assertIn("988", result)
        self.assertIn("988 Suicide & Crisis Lifeline", result)

    def test_single_concise_recommendation_is_returned_unchanged(self):
        recommendation = "Call 988 now. It is available 24/7 in the United States."
        response = SimpleNamespace(
            id="response-1",
            output=[],
            output_text=recommendation,
        )
        client = SimpleNamespace(responses=FakeResponses([response]))
        result = bridge_agent.invoke_agent(
            client,
            "MindBridge",
            "US",
            "English",
            "I need crisis support.",
            self.provider,
        )
        self.assertEqual(result, recommendation)
        self.assertNotIn("\n", result)

    def test_unverified_model_number_is_replaced_by_verified_record(self):
        response = SimpleNamespace(
            id="response-1",
            output=[],
            output_text="Call 12345 for help.",
        )
        client = SimpleNamespace(responses=FakeResponses([response]))
        result = bridge_agent.invoke_agent(
            client,
            "MindBridge",
            "UK",
            "English",
            "I feel burned out.",
            self.provider,
        )
        self.assertIn("116 123", result)
        self.assertNotIn("12345", result)

    def test_unsupported_country_gets_number_free_fallback(self):
        response = SimpleNamespace(id="response-1", output=[], output_text="")
        client = SimpleNamespace(responses=FakeResponses([response]))
        result = bridge_agent.invoke_agent(
            client,
            "MindBridge",
            "France",
            "French",
            "I need support.",
            self.provider,
        )
        self.assertIn("do not have a verified helpline", result)
        self.assertNotRegex(result, r"\b(988|911|999|112|1553)\b")

    def test_bridge_service_reports_foundry_source_for_verified_response(self):
        response = SimpleNamespace(
            id="response-1",
            output=[],
            output_text="Call 988 now. It is available 24/7 in the United States.",
        )
        client = SimpleNamespace(responses=FakeResponses([response]))
        service = bridge_agent.BridgeService(client, "MindBridge", self.provider)
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="US",
                language="English",
                situation="I need crisis support.",
            )
        )
        self.assertEqual(result.source, "foundry_agent")
        self.assertEqual(result.severity, "support")
        self.assertTrue(result.escalated)

    def test_foundry_iq_mcp_result_is_primary_source(self):
        response = SimpleNamespace(
            id="response-1",
            output=[
                SimpleNamespace(
                    type="mcp_call",
                    server_label="kb-mindbridge-crisis-k-8pcp2",
                )
            ],
            output_text=(
                "Call 13 11 14, Lifeline Australia. It is available 24/7 "
                "in Australia."
            ),
        )
        client = SimpleNamespace(responses=FakeResponses([response]))
        service = bridge_agent.BridgeService(client, "MindBridge", self.provider)
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="Australia",
                language="English",
                situation="I need crisis support.",
            )
        )
        self.assertEqual(result.source, "foundry_iq")
        self.assertIn("13 11 14", result.message)
        self.assertEqual(len(client.responses.calls), 1)

    def test_foundry_iq_no_match_falls_back_without_inventing_number(self):
        first = SimpleNamespace(
            id="response-1",
            output=[
                SimpleNamespace(
                    type="mcp_call",
                    server_label="kb-mindbridge-crisis-k-8pcp2",
                ),
                SimpleNamespace(
                    type="function_call",
                    name=bridge_agent.LOOKUP_TOOL_NAME,
                    arguments=json.dumps(
                        {"country": "Canada", "language": "French"}
                    ),
                    call_id="call-1",
                ),
            ],
            output_text="",
        )
        second = SimpleNamespace(
            id="response-2",
            output=[],
            output_text="Call 988, Talk Suicide Canada. It is available 24/7.",
        )
        client = SimpleNamespace(responses=FakeResponses([first, second]))
        service = bridge_agent.BridgeService(client, "MindBridge", self.provider)
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="Canada",
                language="French",
                situation="I need support.",
            )
        )
        self.assertEqual(result.source, "local_safety_fallback")
        self.assertIn("988", result.message)
        self.assertNotIn("12345", result.message)

    def test_foundry_iq_http_error_uses_local_fallback(self):
        request = Request("POST", "https://example.invalid/responses")
        response = Response(400, request=request)
        error = BadRequestError(
            "Foundry IQ MCP access denied",
            response=response,
            body={"error": {"message": "403 Forbidden"}},
        )
        responses = MagicMock()
        responses.create.side_effect = error
        client = SimpleNamespace(responses=responses)
        service = bridge_agent.BridgeService(client, "MindBridge", self.provider)
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="Canada",
                language="French",
                situation="I need crisis support.",
            )
        )
        self.assertEqual(result.source, "local_safety_fallback")
        self.assertIn("988", result.message)

    def test_bridge_service_reports_local_source_for_unverified_response(self):
        response = SimpleNamespace(
            id="response-1",
            output=[],
            output_text="Call an invented number.",
        )
        client = SimpleNamespace(responses=FakeResponses([response]))
        service = bridge_agent.BridgeService(client, "MindBridge", self.provider)
        result = service.recommend(
            bridge_agent.BridgeRequest(
                country="Philippines",
                language="Filipino",
                situation="I need support.",
            )
        )
        self.assertEqual(result.source, "local_safety_fallback")
        self.assertIn("1553", result.message)


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.settings = bridge_agent.Settings(
            project_endpoint="https://example.invalid",
            model_deployment_name="test-model",
            agent_name="MindBridge",
            foundry_iq_kb_name="mindbridge-crisis-kb",
            foundry_iq_knowledge_source_name="global-crisis-resources",
            foundry_iq_mcp_server_label="kb-label",
            foundry_iq_mcp_server_url="https://example.invalid/kb/mcp",
            foundry_iq_project_connection_id="kb-connection",
        )

    def test_existing_agent_is_reused(self):
        project_client = MagicMock()
        existing = SimpleNamespace(name="MindBridge")
        project_client.agents.get.return_value = existing
        result = bridge_agent.ensure_agent(
            project_client,
            self.settings,
            provision=False,
        )
        self.assertIs(result, existing)
        project_client.agents.create_version.assert_not_called()

    def test_missing_agent_is_provisioned(self):
        project_client = MagicMock()
        project_client.agents.get.side_effect = ResourceNotFoundError("missing")
        created = SimpleNamespace(name="MindBridge", version="1")
        project_client.agents.create_version.return_value = created
        result = bridge_agent.ensure_agent(
            project_client,
            self.settings,
            provision=False,
        )
        self.assertIs(result, created)
        project_client.agents.create_version.assert_called_once()

    def test_provision_flag_forces_new_version(self):
        project_client = MagicMock()
        bridge_agent.ensure_agent(
            project_client,
            self.settings,
            provision=True,
        )
        project_client.agents.get.assert_not_called()
        project_client.agents.create_version.assert_called_once()

    def test_agent_definition_contains_foundry_iq_before_fallback(self):
        definition = bridge_agent.build_agent_definition(self.settings)
        self.assertEqual(definition.tools[0].type, "mcp")
        self.assertEqual(definition.tools[0].server_label, "kb-label")
        self.assertEqual(definition.tools[1].type, "function")
        self.assertEqual(definition.tools[1].name, bridge_agent.LOOKUP_TOOL_NAME)


if __name__ == "__main__":
    unittest.main()
