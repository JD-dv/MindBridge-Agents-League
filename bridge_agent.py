"""MindBridge crisis-resource CLI backed by a Microsoft Foundry prompt agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal, Protocol, Sequence

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, MCPTool, PromptAgentDefinition
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError


EXIT_CONFIG = 2
EXIT_AUTH = 3
EXIT_SERVICE = 4
EXIT_RESPONSE = 5

LOOKUP_TOOL_NAME = "lookup_verified_helpline"
# Foundry IQ can take longer on a cold knowledge-base request.
RESPONSE_TIMEOUT_SECONDS = 60.0
QUIT_COMMANDS = {"quit", "exit"}
IMMEDIATE_DANGER_TERMS = (
    "kill myself",
    "end my life",
    "suicide",
    "suicidal",
    "hurt myself",
    "harm myself",
    "overdose",
    "have a gun",
    "have a weapon",
    "can't stay safe",
    "cannot stay safe",
    "immediate danger",
    "about to do it",
)


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment_name: str
    agent_name: str
    foundry_iq_kb_name: str
    foundry_iq_knowledge_source_name: str
    foundry_iq_mcp_server_label: str
    foundry_iq_mcp_server_url: str
    foundry_iq_project_connection_id: str


@dataclass(frozen=True)
class BridgeRequest:
    country: str
    language: str
    situation: str


@dataclass(frozen=True)
class BridgeRecommendation:
    message: str
    severity: Literal["support", "immediate_danger"]
    source: Literal["foundry_iq", "foundry_agent", "local_safety_fallback"]
    escalated: bool


@dataclass(frozen=True)
class HelplineRecord:
    country: str
    country_code: str
    service: str
    number: str
    availability: str
    languages: tuple[str, ...]
    source_url: str
    verified_on: date
    emergency_number: str

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["languages"] = list(self.languages)
        value["verified_on"] = self.verified_on.isoformat()
        return value


class HelplineProvider(Protocol):
    """Stable lookup contract for the reviewed local safety fallback."""

    def lookup(self, country: str, language: str = "English") -> HelplineRecord | None:
        """Return a verified record for a supported country."""


class SeedHelplineProvider:
    """Small, reviewed demo dataset. This is not a global directory."""

    _RECORDS = (
        HelplineRecord(
            country="United Kingdom",
            country_code="GB",
            service="Samaritans",
            number="116 123",
            availability="Free, 24 hours a day",
            languages=("English",),
            source_url="https://www.samaritans.org/how-we-can-help/contact-samaritan/",
            verified_on=date(2026, 6, 11),
            emergency_number="999 or 112",
        ),
        HelplineRecord(
            country="United States",
            country_code="US",
            service="988 Suicide & Crisis Lifeline",
            number="988",
            availability="Call, text, or chat, 24/7",
            languages=("English", "Spanish"),
            source_url="https://988lifeline.org/",
            verified_on=date(2026, 6, 11),
            emergency_number="911",
        ),
        HelplineRecord(
            country="Canada",
            country_code="CA",
            service="Talk Suicide Canada",
            number="988",
            availability="24/7",
            languages=("English", "French"),
            source_url="data/helplines.csv",
            verified_on=date(2026, 6, 12),
            emergency_number="911",
        ),
        HelplineRecord(
            country="Australia",
            country_code="AU",
            service="Lifeline Australia",
            number="13 11 14",
            availability="24/7",
            languages=("English",),
            source_url="data/helplines.csv",
            verified_on=date(2026, 6, 12),
            emergency_number="000",
        ),
        HelplineRecord(
            country="Philippines",
            country_code="PH",
            service="National Center for Mental Health Crisis Hotline",
            number="1553",
            availability="24/7 crisis hotline",
            languages=("English", "Filipino"),
            source_url=(
                "https://pia.gov.ph/news/luzon/"
                "doh-mental-health-programs-crisis-hotlines-available-this-undas/"
            ),
            verified_on=date(2026, 6, 11),
            emergency_number="911",
        ),
    )
    _ALIASES = {
        "gb": "GB",
        "great britain": "GB",
        "uk": "GB",
        "u.k.": "GB",
        "united kingdom": "GB",
        "england": "GB",
        "scotland": "GB",
        "wales": "GB",
        "northern ireland": "GB",
        "us": "US",
        "u.s.": "US",
        "usa": "US",
        "u.s.a.": "US",
        "united states": "US",
        "united states of america": "US",
        "america": "US",
        "ph": "PH",
        "phl": "PH",
        "philippines": "PH",
        "the philippines": "PH",
        "pilipinas": "PH",
        "ca": "CA",
        "can": "CA",
        "canada": "CA",
        "au": "AU",
        "aus": "AU",
        "australia": "AU",
    }

    def lookup(self, country: str, language: str = "English") -> HelplineRecord | None:
        del language  # The reviewed fallback returns the country record as stored.
        normalized = " ".join(country.strip().lower().split())
        country_code = self._ALIASES.get(normalized)
        if not country_code:
            return None
        return next(record for record in self._RECORDS if record.country_code == country_code)


SYSTEM_INSTRUCTIONS = """\
You are The Bridge Agent, a calm crisis-resource navigator for men's mental health.

Your task:
1. Internally assess whether the situation is general distress, burnout, grief, acute
   crisis, or immediate danger. Never reveal private chain-of-thought or claim to diagnose.
2. Use the attached Microsoft Foundry IQ knowledge base first to retrieve the verified
   crisis resource for the user's country and preferred language.
3. If Foundry IQ fails, times out, or returns no usable country match, call
   lookup_verified_helpline as the deterministic safety fallback.
4. Never name a service or phone number unless it came from Foundry IQ or the fallback tool.
5. Return exactly one primary recommendation in plain language. Keep it under 80 words.
6. Include the service, contact method or number, availability, country, and whether the
   requested language is listed when those facts are present in the tool result.
7. If the lookup is unsupported, ask for the user's country and advise them to contact
   local emergency services if they may act now. Do not provide a guessed number.
8. If the user may be in immediate danger, lead with local emergency services and ask
   them to get near a trusted person. The application may also enforce this locally.

Do not provide therapy, a diagnosis, or a list of competing resources. Be direct, warm,
and action-oriented.
"""


def load_settings() -> Settings:
    load_dotenv(override=False)
    names = (
        "PROJECT_ENDPOINT",
        "MODEL_DEPLOYMENT_NAME",
        "AGENT_NAME",
        "FOUNDRY_IQ_KB_NAME",
        "FOUNDRY_IQ_KNOWLEDGE_SOURCE_NAME",
        "FOUNDRY_IQ_MCP_SERVER_LABEL",
        "FOUNDRY_IQ_MCP_SERVER_URL",
        "FOUNDRY_IQ_PROJECT_CONNECTION_ID",
    )
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise ValueError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Add them to the workspace .env file."
        )
    return Settings(
        project_endpoint=os.environ["PROJECT_ENDPOINT"].strip(),
        model_deployment_name=os.environ["MODEL_DEPLOYMENT_NAME"].strip(),
        agent_name=os.environ["AGENT_NAME"].strip(),
        foundry_iq_kb_name=os.environ["FOUNDRY_IQ_KB_NAME"].strip(),
        foundry_iq_knowledge_source_name=os.environ[
            "FOUNDRY_IQ_KNOWLEDGE_SOURCE_NAME"
        ].strip(),
        foundry_iq_mcp_server_label=os.environ[
            "FOUNDRY_IQ_MCP_SERVER_LABEL"
        ].strip(),
        foundry_iq_mcp_server_url=os.environ["FOUNDRY_IQ_MCP_SERVER_URL"].strip(),
        foundry_iq_project_connection_id=os.environ[
            "FOUNDRY_IQ_PROJECT_CONNECTION_ID"
        ].strip(),
    )


def build_lookup_tool() -> FunctionTool:
    return FunctionTool(
        name=LOOKUP_TOOL_NAME,
        description=(
            "Look up one reviewed crisis helpline for a country. "
            "This tool is the only allowed source of helpline names and numbers."
        ),
        strict=True,
        parameters={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "The user's country name or country code.",
                },
                "language": {
                    "type": "string",
                    "description": "The user's preferred response language.",
                },
            },
            "required": ["country", "language"],
            "additionalProperties": False,
        },
    )


def build_foundry_iq_tool(settings: Settings) -> MCPTool:
    return MCPTool(
        server_label=settings.foundry_iq_mcp_server_label,
        server_url=settings.foundry_iq_mcp_server_url,
        project_connection_id=settings.foundry_iq_project_connection_id,
        require_approval="never",
        server_description=(
            f"Microsoft Foundry IQ knowledge base {settings.foundry_iq_kb_name} "
            f"using knowledge source {settings.foundry_iq_knowledge_source_name}. "
            "Use it first for grounded crisis-resource retrieval."
        ),
    )


def build_agent_definition(settings: Settings) -> PromptAgentDefinition:
    return PromptAgentDefinition(
        model=settings.model_deployment_name,
        instructions=SYSTEM_INSTRUCTIONS,
        temperature=0.1,
        tools=[build_foundry_iq_tool(settings), build_lookup_tool()],
        tool_choice="auto",
    )


def ensure_agent(
    project_client: AIProjectClient,
    settings: Settings,
    *,
    provision: bool,
) -> Any:
    if not provision:
        try:
            return project_client.agents.get(settings.agent_name)
        except ResourceNotFoundError:
            pass

    return project_client.agents.create_version(
        agent_name=settings.agent_name,
        definition=build_agent_definition(settings),
        description="MindBridge verified crisis-resource navigator",
        metadata={
            "project": "MindBridge",
            "microsoft_iq_layer": "Foundry IQ",
            "knowledge_base": settings.foundry_iq_kb_name,
            "knowledge_source": settings.foundry_iq_knowledge_source_name,
        },
    )


def is_immediate_danger(situation: str) -> bool:
    normalized = situation.casefold()
    return any(term in normalized for term in IMMEDIATE_DANGER_TERMS)


def immediate_danger_message(
    country: str,
    provider: HelplineProvider,
) -> str:
    record = provider.lookup(country)
    if record:
        return (
            f"Call {record.emergency_number} now or go to the nearest emergency department. "
            "Move near someone you trust and tell them you may not be safe alone."
        )
    return (
        "Call your local emergency services now or go to the nearest emergency department. "
        "Move near someone you trust and tell them you may not be safe alone."
    )


def lookup_tool_result(
    provider: HelplineProvider,
    arguments_json: str,
) -> str:
    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise ValueError("The agent returned malformed lookup arguments.") from exc

    if not isinstance(arguments, dict):
        raise ValueError("The helpline lookup arguments must be a JSON object.")
    country = arguments.get("country")
    language = arguments.get("language")
    if not isinstance(country, str) or not country.strip():
        raise ValueError("The helpline lookup requires a country.")
    if not isinstance(language, str) or not language.strip():
        raise ValueError("The helpline lookup requires a language.")

    record = provider.lookup(country, language)
    if record is None:
        return json.dumps(
            {
                "status": "unsupported",
                "country_requested": country,
                "instruction": (
                    "Do not provide a helpline name or number. Ask for a supported country "
                    "or advise local emergency services if there is immediate danger."
                ),
            }
        )

    return json.dumps(
        {
            "status": "verified",
            "requested_language": language,
            "record": record.to_public_dict(),
        }
    )


def format_verified_recommendation(
    record: HelplineRecord,
    language: str,
) -> str:
    listed_languages = {item.casefold() for item in record.languages}
    if language.casefold() in listed_languages:
        language_note = f"{language} is listed as supported."
    else:
        language_note = (
            f"{language} is not listed in this demo record; ask the service about "
            "language support."
        )
    return (
        f"Call {record.number}, {record.service}. {record.availability}. "
        f"{language_note} {record.country}."
    )


def unsupported_country_message(country: str) -> str:
    display_country = country.strip() or "that location"
    return (
        f"I do not have a verified helpline for {display_country}. "
        "If you may act now, contact local emergency services or go to the nearest "
        "emergency department and stay near someone you trust."
    )


def is_verified_recommendation(text: str, record: HelplineRecord) -> bool:
    return bool(text.strip()) and record.number in text and len(text.split()) <= 80


def build_user_input(country: str, language: str, situation: str) -> str:
    return (
        f"Country: {country.strip()}\n"
        f"Preferred language: {language.strip() or 'English'}\n"
        f"Situation: {situation.strip()}"
    )


def invoke_agent(
    openai_client: Any,
    agent_name: str,
    country: str,
    language: str,
    situation: str,
    provider: HelplineProvider,
    *,
    max_tool_rounds: int = 3,
) -> str:
    recommendation, _source = invoke_agent_detailed(
        openai_client,
        agent_name,
        country,
        language,
        situation,
        provider,
        max_tool_rounds=max_tool_rounds,
    )
    return recommendation


def invoke_agent_detailed(
    openai_client: Any,
    agent_name: str,
    country: str,
    language: str,
    situation: str,
    provider: HelplineProvider,
    *,
    max_tool_rounds: int = 3,
) -> tuple[
    str,
    Literal["foundry_iq", "foundry_agent", "local_safety_fallback"],
]:
    known_record = provider.lookup(country, language)
    foundry_iq_used = False
    fallback_tool_used = False
    try:
        response = openai_client.responses.create(
            input=build_user_input(country, language, situation),
            extra_body={
                "agent_reference": {
                    "name": agent_name,
                    "type": "agent_reference",
                }
            },
            timeout=RESPONSE_TIMEOUT_SECONDS,
        )
    except (APIConnectionError, APITimeoutError, APIStatusError):
        if known_record:
            return (
                format_verified_recommendation(known_record, language),
                "local_safety_fallback",
            )
        return unsupported_country_message(country), "local_safety_fallback"

    for _ in range(max_tool_rounds):
        foundry_iq_used = foundry_iq_used or any(
            str(getattr(item, "type", "")).startswith("mcp_")
            for item in getattr(response, "output", [])
        )
        tool_calls = [
            item
            for item in getattr(response, "output", [])
            if getattr(item, "type", None) == "function_call"
        ]
        if not tool_calls:
            output_text = getattr(response, "output_text", "")
            if (
                isinstance(output_text, str)
                and known_record
                and is_verified_recommendation(output_text, known_record)
            ):
                if foundry_iq_used and not fallback_tool_used:
                    return output_text.strip(), "foundry_iq"
                if fallback_tool_used:
                    return output_text.strip(), "local_safety_fallback"
                return output_text.strip(), "foundry_agent"
            if known_record:
                return (
                    format_verified_recommendation(known_record, language),
                    "local_safety_fallback",
                )
            return unsupported_country_message(country), "local_safety_fallback"

        tool_outputs = []
        for tool_call in tool_calls:
            if getattr(tool_call, "name", None) != LOOKUP_TOOL_NAME:
                raise ValueError(f"The agent requested an unsupported tool: {tool_call.name}")
            result = lookup_tool_result(provider, tool_call.arguments)
            fallback_tool_used = True
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": result,
                }
            )

        try:
            response = openai_client.responses.create(
                input=tool_outputs,
                previous_response_id=response.id,
                extra_body={
                    "agent_reference": {
                        "name": agent_name,
                        "type": "agent_reference",
                    }
                },
                timeout=RESPONSE_TIMEOUT_SECONDS,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError):
            if known_record:
                return (
                    format_verified_recommendation(known_record, language),
                    "local_safety_fallback",
                )
            return unsupported_country_message(country), "local_safety_fallback"

    raise ValueError("The agent exceeded the allowed number of tool calls.")


class BridgeService:
    """Reusable Bridge interface for the CLI, dashboard, and WorkWell handoff."""

    def __init__(
        self,
        openai_client: Any,
        agent_name: str,
        provider: HelplineProvider | None = None,
    ) -> None:
        self.openai_client = openai_client
        self.agent_name = agent_name
        self.provider = provider or SeedHelplineProvider()

    def recommend(self, request: BridgeRequest) -> BridgeRecommendation:
        if is_immediate_danger(request.situation):
            return BridgeRecommendation(
                message=immediate_danger_message(request.country, self.provider),
                severity="immediate_danger",
                source="local_safety_fallback",
                escalated=True,
            )

        message, source = invoke_agent_detailed(
            self.openai_client,
            self.agent_name,
            request.country,
            request.language,
            request.situation,
            self.provider,
        )
        return BridgeRecommendation(
            message=message,
            severity="support",
            source=source,
            escalated=True,
        )


def get_recommendation(
    openai_client: Any,
    agent_name: str,
    country: str,
    language: str,
    situation: str,
    provider: HelplineProvider,
) -> str:
    return BridgeService(openai_client, agent_name, provider).recommend(
        BridgeRequest(
            country=country,
            language=language,
            situation=situation,
        )
    ).message


def run_bridge_request(
    request: BridgeRequest,
    *,
    provision: bool = False,
) -> BridgeRecommendation:
    """Run one Bridge request with managed Azure clients."""
    settings = load_settings()
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=settings.project_endpoint,
            credential=credential,
        ) as project_client,
    ):
        ensure_agent(project_client, settings, provision=provision)
        with project_client.get_openai_client(
            max_retries=0,
            timeout=RESPONSE_TIMEOUT_SECONDS,
        ) as openai_client:
            return BridgeService(openai_client, settings.agent_name).recommend(request)


def prompt_value(label: str, *, default: str | None = None) -> str | None:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if value.casefold() in QUIT_COMMANDS:
        return None
    return value or default or ""


def run_interactive(
    openai_client: Any,
    agent_name: str,
    provider: HelplineProvider,
) -> int:
    print("MindBridge - The Bridge Agent")
    print("Type 'quit' or 'exit' at any prompt.\n")

    while True:
        country = prompt_value("Country")
        if country is None:
            return 0
        language = prompt_value("Preferred language", default="English")
        if language is None:
            return 0
        situation = prompt_value("What is happening?")
        if situation is None:
            return 0
        if not country or not situation:
            print("Please provide both a country and a brief description.\n")
            continue

        try:
            recommendation = get_recommendation(
                openai_client,
                agent_name,
                country,
                language or "English",
                situation,
                provider,
            )
        except ClientAuthenticationError as exc:
            print(f"\nAuthentication error: {friendly_error(exc)}\n", file=sys.stderr)
            return EXIT_AUTH
        except (HttpResponseError, APIStatusError, APIConnectionError) as exc:
            print(f"\nService error: {friendly_error(exc)}\n", file=sys.stderr)
            return EXIT_SERVICE
        except ValueError as exc:
            print(f"\nResponse error: {friendly_error(exc)}\n", file=sys.stderr)
            return EXIT_RESPONSE

        print(f"\n{recommendation}\n")


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, ClientAuthenticationError):
        return "Azure authentication failed. Run 'az login' and verify your Foundry access."
    if isinstance(exc, HttpResponseError):
        if exc.status_code == 429:
            return "The Foundry service is busy. Please wait briefly and try again."
        if exc.status_code in (401, 403):
            return "Azure denied access. Check your login and Foundry project role."
        return f"Foundry returned an error ({exc.status_code or 'unknown status'})."
    if isinstance(exc, APITimeoutError):
        return "The Foundry model timed out. Please try again."
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return "The Foundry service is busy. Please wait briefly and try again."
        if exc.status_code in (401, 403):
            return "Azure denied access. Check your login and Foundry project role."
        return f"Foundry returned an error ({exc.status_code})."
    if isinstance(exc, APIConnectionError):
        return "Could not connect to Foundry. Check your network and try again."
    return str(exc)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the MindBridge verified crisis-resource navigator."
    )
    parser.add_argument(
        "--provision",
        action="store_true",
        help="Create a new version of the configured Foundry prompt agent before starting.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    provider = SeedHelplineProvider()
    try:
        with (
            DefaultAzureCredential() as credential,
            AIProjectClient(
                endpoint=settings.project_endpoint,
                credential=credential,
            ) as project_client,
        ):
            ensure_agent(project_client, settings, provision=args.provision)
            with project_client.get_openai_client(
                max_retries=0,
                timeout=RESPONSE_TIMEOUT_SECONDS,
            ) as openai_client:
                return run_interactive(openai_client, settings.agent_name, provider)
    except ClientAuthenticationError as exc:
        print(f"Authentication error: {friendly_error(exc)}", file=sys.stderr)
        return EXIT_AUTH
    except (
        HttpResponseError,
        APIStatusError,
        APIConnectionError,
        RuntimeError,
    ) as exc:
        print(f"Service error: {friendly_error(exc)}", file=sys.stderr)
        return EXIT_SERVICE
    except ValueError as exc:
        print(f"Response error: {friendly_error(exc)}", file=sys.stderr)
        return EXIT_RESPONSE


if __name__ == "__main__":
    raise SystemExit(main())
