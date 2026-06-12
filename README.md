# MindBridge

MindBridge is a hackathon prototype combining workplace support guidance with
verified crisis-resource navigation.

## WorkWell Prototype

The Streamlit dashboard demonstrates:

- A synthetic team overview based on observable workplace-pattern changes
- Suggested private manager check-ins
- Individual manager coaching and conversation starters
- A manager-confirmed escalation handoff to The Bridge Agent

> All people, signals, and workplace data shown are synthetic demo data. MindBridge does not diagnose mental health conditions.

The prototype contains no real names, emails, employee identifiers, employers,
Teams messages, calendar content, or company data. WorkWell groups profiles by
workplace support level and does not rank people by mental-health risk.

## Run Locally

```bash
source .venv/bin/activate
streamlit run app.py
```

The existing Bridge CLI remains available:

```bash
python bridge_agent.py
```

## Current Grounding

MindBridge uses Microsoft Foundry IQ as the Microsoft IQ layer for grounded
crisis-resource retrieval.

The Bridge Agent queries the `mindbridge-crisis-kb` knowledge base, backed by
Azure AI Search and the `global-crisis-resources` knowledge source. The
knowledge base contains the reviewed `helplines.csv` dataset.

Retrieval follows this order:

1. Microsoft Foundry IQ knowledge-base retrieval
2. Validation against the reviewed country record
3. Local `lookup_verified_helpline` fallback when Foundry IQ fails, times out,
   or returns no usable match

The deterministic immediate-danger path remains local so urgent guidance does
not depend on a network request.
