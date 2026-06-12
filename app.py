"""MindBridge Streamlit demo: WorkWell prevention to Bridge crisis support."""

from __future__ import annotations

import streamlit as st

from bridge_agent import (
    APIConnectionError,
    APIStatusError,
    BridgeRecommendation,
    ClientAuthenticationError,
    HttpResponseError,
    friendly_error,
    run_bridge_request,
)
from workwell_agent import (
    SCENARIOS,
    SYNTHETIC_TEAM,
    RiskLevel,
    SyntheticEmployee,
    WorkSignals,
    assess_signals,
    assess_team,
    build_bridge_request,
)


LEVEL_LABELS = {
    RiskLevel.NORMAL: "Normal",
    RiskLevel.EARLY_WARNING: "Early warning",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.ESCALATE: "Escalate",
}
LEVEL_COLORS = {
    RiskLevel.NORMAL: "#2e7d62",
    RiskLevel.EARLY_WARNING: "#b7791f",
    RiskLevel.MODERATE: "#c05621",
    RiskLevel.ESCALATE: "#b42318",
}
SYNTHETIC_DATA_NOTICE = (
    "All people, signals, and workplace data shown are synthetic demo data. "
    "MindBridge does not diagnose mental health conditions."
)


def configure_page() -> None:
    st.set_page_config(
        page_title="MindBridge | WorkWell",
        page_icon="MB",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        :root {
            --mb-ink: #17213a;
            --mb-muted: #667085;
            --mb-border: #d9deea;
            --mb-surface: #ffffff;
            --mb-primary: #5b5fc7;
            --mb-primary-dark: #4549a5;
        }
        .stApp {
            background:
                radial-gradient(circle at 90% 0%, rgba(91, 95, 199, .10), transparent 28rem),
                #f5f7fb;
            color: var(--mb-ink);
        }
        .block-container { max-width: 1240px; padding-top: 1.5rem; padding-bottom: 3rem; }
        h1, h2, h3, h4, p, label, .stCaption { color: var(--mb-ink); }
        .hero {
            position: relative; overflow: hidden;
            padding: 1.65rem 1.8rem; border-radius: 20px;
            background: linear-gradient(120deg, #20204f, #5b5fc7 65%, #777af0);
            color: white; margin-bottom: 1rem;
            box-shadow: 0 14px 34px rgba(50, 50, 130, .20);
        }
        .hero::after {
            content: ""; position: absolute; width: 220px; height: 220px;
            border-radius: 50%; right: -60px; top: -105px;
            background: rgba(255, 255, 255, .12);
        }
        .hero h1 { margin: 0; font-size: 2.1rem; color: white; }
        .hero p { margin: .45rem 0 0; opacity: .9; color: white; }
        .panel {
            background: var(--mb-surface); border: 1px solid var(--mb-border);
            border-radius: 16px; padding: 1rem 1.15rem;
            box-shadow: 0 5px 18px rgba(34, 40, 74, .07);
        }
        .risk {
            color: white; padding: .75rem 1rem; border-radius: 12px;
            font-weight: 700; font-size: 1.05rem;
            box-shadow: 0 5px 14px rgba(23, 33, 58, .12);
        }
        .source {
            display: inline-block; padding: .25rem .6rem; border-radius: 999px;
            background: #eef0ff; color: #3f43a5; font-size: .82rem;
        }
        .metric-card {
            background: white; border: 1px solid var(--mb-border);
            border-radius: 14px; padding: .9rem 1rem; min-height: 104px;
            box-shadow: 0 4px 14px rgba(34, 40, 74, .05);
        }
        .metric-card .value {
            color: #363a92; font-size: 1.55rem; font-weight: 750; line-height: 1.2;
        }
        .metric-card .label {
            color: var(--mb-muted); font-size: .84rem; margin-top: .25rem;
        }
        .team-card {
            background: white; border: 1px solid var(--mb-border);
            border-radius: 16px; padding: 1rem 1.1rem; margin-bottom: .75rem;
            box-shadow: 0 4px 14px rgba(34, 40, 74, .05);
        }
        .team-card h4 { margin: 0; }
        .team-card p { margin: .35rem 0; }
        .support-pill {
            display: inline-block; color: white; padding: .22rem .55rem;
            border-radius: 999px; font-size: .76rem; font-weight: 700;
        }
        div[data-testid="stForm"] {
            background: rgba(255, 255, 255, .82);
            border: 1px solid var(--mb-border);
            border-radius: 18px;
            padding: 1.15rem;
            box-shadow: 0 5px 18px rgba(34, 40, 74, .05);
        }
        div[data-testid="stAlert"] {
            border-radius: 14px;
            border: 1px solid rgba(91, 95, 199, .18);
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        div[data-baseweb="textarea"] > div {
            background: white;
            border-color: var(--mb-border);
            color: var(--mb-ink);
        }
        div[data-baseweb="select"] *,
        div[data-baseweb="input"] *,
        div[data-baseweb="textarea"] * {
            color: var(--mb-ink) !important;
        }
        div.stButton > button[kind="secondary"],
        div.stButton > button[data-testid="stBaseButton-secondary"] {
            background: #ffffff !important;
            color: #3f43a5 !important;
            border: 1px solid #aeb2ea !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            box-shadow: 0 2px 7px rgba(63, 67, 165, .10);
        }
        div.stButton > button[kind="secondary"]:hover,
        div.stButton > button[data-testid="stBaseButton-secondary"]:hover {
            background: #eef0ff !important;
            color: #30348f !important;
            border-color: #777af0 !important;
        }
        div.stButton > button[kind="secondary"]:focus,
        div.stButton > button[data-testid="stBaseButton-secondary"]:focus {
            background: #ffffff !important;
            color: #30348f !important;
            border-color: #5b5fc7 !important;
            box-shadow: 0 0 0 3px rgba(91, 95, 199, .20) !important;
        }
        div.stButton > button[kind="secondary"]:disabled,
        div.stButton > button[data-testid="stBaseButton-secondary"]:disabled {
            background: #f2f4f7 !important;
            color: #98a2b3 !important;
            border-color: #d0d5dd !important;
        }
        div.stButton > button[kind="primary"],
        div.stButton > button[data-testid="stBaseButton-primary"],
        div[data-testid="stFormSubmitButton"] > button {
            background: var(--mb-primary) !important;
            color: white !important;
            border: 1px solid var(--mb-primary) !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            box-shadow: 0 5px 12px rgba(91, 95, 199, .22);
        }
        div.stButton > button[kind="primary"]:hover,
        div.stButton > button[data-testid="stBaseButton-primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            background: var(--mb-primary-dark) !important;
            border-color: var(--mb-primary-dark) !important;
            color: white !important;
        }
        div.stButton > button[kind="primary"]:focus,
        div.stButton > button[data-testid="stBaseButton-primary"]:focus,
        div[data-testid="stFormSubmitButton"] > button:focus {
            color: white !important;
            box-shadow: 0 0 0 3px rgba(91, 95, 199, .25) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def reset_demo() -> None:
    st.session_state.clear()
    st.session_state["scenario"] = "Potential crisis"


def render_header() -> None:
    st.markdown(
        """
        <div class="hero">
          <h1>MindBridge</h1>
          <p>WorkWell catches early. The Bridge catches crisis.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        SYNTHETIC_DATA_NOTICE
        + " Teams and Work IQ behavior is simulated; no Microsoft 365 data is accessed."
    )


def select_employee_for_review(employee: SyntheticEmployee) -> None:
    st.session_state["selected_employee_name"] = employee.first_name
    st.session_state["scenario"] = f"Synthetic profile: {employee.first_name}"
    st.session_state["review_signals"] = employee.signals
    st.session_state.pop("assessment", None)
    st.session_state.pop("bridge_result", None)


def render_signal_form() -> WorkSignals | None:
    st.subheader("WorkWell signal review")
    selected_employee_name = st.session_state.get("selected_employee_name")
    if selected_employee_name:
        st.caption(
            f"Private review for synthetic profile: {selected_employee_name}. "
            "Confirm the signals below before assessment."
        )
        scenario_name = f"Synthetic profile: {selected_employee_name}"
        scenario = st.session_state["review_signals"]
        if st.button("Return to manual scenarios"):
            st.session_state.pop("selected_employee_name", None)
            st.session_state.pop("review_signals", None)
            st.session_state.pop("assessment", None)
            st.rerun()
    else:
        scenario_name = st.selectbox(
            "Synthetic scenario",
            list(SCENARIOS),
            index=list(SCENARIOS).index("Potential crisis"),
            key="scenario",
        )
        scenario = SCENARIOS[scenario_name]

    with st.form("signal_form"):
        left, right = st.columns(2)
        with left:
            missed = st.slider(
                "Missed check-ins",
                0,
                4,
                scenario.missed_check_ins,
                key=f"missed_{scenario_name}",
            )
            participation = st.slider(
                "Meeting participation drop",
                0,
                100,
                scenario.participation_drop,
                format="%d%%",
                key=f"participation_{scenario_name}",
            )
        with right:
            delay = st.slider(
                "Response-time change",
                1.0,
                5.0,
                scenario.response_delay,
                step=0.5,
                format="%.1fx",
                key=f"delay_{scenario_name}",
            )
            concern = st.slider(
                "Manager concern",
                0,
                3,
                scenario.manager_concern,
                key=f"concern_{scenario_name}",
            )
        submitted = st.form_submit_button(
            "Run private assessment",
            type="primary",
            use_container_width=True,
        )
    if not submitted:
        return None
    return WorkSignals(missed, participation, delay, concern)


def render_metric(label: str, value: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="value">{value}</div>'
        f'<div class="label">{label}</div></div>',
        unsafe_allow_html=True,
    )


def render_team_overview() -> None:
    overview = assess_team()
    st.subheader("Synthetic team overview")
    st.caption(
        "WorkWell compares each fictional profile with its own synthetic baseline. "
        "It suggests private check-ins; it does not rank mental-health risk."
    )

    metric_columns = st.columns(4)
    with metric_columns[0]:
        render_metric("Synthetic people", str(len(overview.members)))
    with metric_columns[1]:
        render_metric("Missed check-ins", str(overview.total_missed_check_ins))
    with metric_columns[2]:
        render_metric(
            "Average participation change",
            f"{overview.average_participation_drop:.0f}% down",
        )
    with metric_columns[3]:
        render_metric(
            "Average response-time change",
            f"{overview.average_response_delay:.1f}x",
        )

    st.markdown("#### Support-level distribution")
    distribution_columns = st.columns(4)
    for column, level in zip(distribution_columns, RiskLevel):
        with column:
            render_metric(LEVEL_LABELS[level], str(overview.level_counts[level]))

    st.markdown("#### Suggested private check-ins")
    st.caption(
        "Grouped by support level. The manager decides whether to open a private review."
    )
    for level in (
        RiskLevel.ESCALATE,
        RiskLevel.MODERATE,
        RiskLevel.EARLY_WARNING,
    ):
        grouped = [
            member
            for member in overview.suggested_check_ins
            if member.assessment.level is level
        ]
        if not grouped:
            continue
        st.markdown(f"##### {LEVEL_LABELS[level]}")
        for member in grouped:
            details, action = st.columns([4, 1.2])
            with details:
                st.markdown(
                    f'<div class="team-card">'
                    f"<h4>{member.employee.first_name}</h4>"
                    f"<p><b>{member.employee.role}</b></p>"
                    f'<span class="support-pill" '
                    f'style="background:{LEVEL_COLORS[level]}">'
                    f"{LEVEL_LABELS[level]}</span>"
                    f"<p><b>Work-pattern signals:</b> {member.signal_summary}</p>"
                    f"<p><b>Suggested manager action:</b> "
                    f"{member.suggested_action}</p></div>",
                    unsafe_allow_html=True,
                )
            with action:
                if st.button(
                    "Review privately",
                    key=f"review_{member.employee.first_name}",
                    use_container_width=True,
                ):
                    select_employee_for_review(member.employee)
                    st.rerun()

    st.markdown("#### All synthetic profiles")
    for member in overview.members:
        st.write(
            f"**{member.employee.first_name} · {member.employee.role}** — "
            f"{member.signal_summary} — **{LEVEL_LABELS[member.assessment.level]}** — "
            f"{member.suggested_action}"
        )


def render_assessment() -> None:
    assessment = st.session_state.get("assessment")
    if not assessment:
        st.markdown(
            '<div class="panel"><b>Assessment ready</b><br>'
            "Choose synthetic signals and run the private review.</div>",
            unsafe_allow_html=True,
        )
        return

    color = LEVEL_COLORS[assessment.level]
    st.markdown(
        f'<div class="risk" style="background:{color}">'
        f'{LEVEL_LABELS[assessment.level]} · score {assessment.score}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("#### Evidence summary")
    for item in assessment.evidence:
        st.write(f"- {item}")
    st.markdown("#### Private manager nudge")
    st.write(assessment.manager_nudge)
    st.markdown("#### Conversation starter")
    st.success(assessment.conversation_starter)


def source_label(result: BridgeRecommendation) -> str:
    if result.source == "foundry_iq":
        return "Microsoft Foundry IQ · mindbridge-crisis-kb"
    if result.source == "foundry_agent":
        return "Microsoft Foundry agent · verified response"
    return "Local verified safety fallback"


def render_bridge_handoff() -> None:
    assessment = st.session_state.get("assessment")
    if not assessment or not assessment.should_escalate:
        return

    st.divider()
    st.subheader("Escalation handoff to The Bridge")
    st.caption(
        "Only the manager-entered concern and selected location are handed off. "
        "Synthetic work telemetry is not sent."
    )
    with st.form("bridge_form"):
        col1, col2 = st.columns(2)
        country = col1.selectbox(
            "Country",
            ("United Kingdom", "United States", "Philippines", "Other"),
        )
        language = col2.text_input("Preferred language", value="English")
        if country == "Other":
            country = st.text_input("Enter country")
        concern = st.text_area(
            "Manager-entered concern",
            value=(
                "The employee said they feel unable to cope and may need crisis support."
            ),
            height=100,
        )
        send = st.form_submit_button(
            "Send private Bridge handoff",
            type="primary",
            use_container_width=True,
        )

    if send:
        request = build_bridge_request(
            assessment,
            country=country,
            language=language,
            concern=concern,
        )
        try:
            with st.spinner("Finding one verified action..."):
                st.session_state["bridge_result"] = run_bridge_request(request)
        except (
            ClientAuthenticationError,
            HttpResponseError,
            APIStatusError,
            APIConnectionError,
            ValueError,
        ) as exc:
            st.error(friendly_error(exc))

    result = st.session_state.get("bridge_result")
    if result:
        st.error(result.message if result.severity == "immediate_danger" else "Support handoff ready")
        if result.severity != "immediate_danger":
            st.markdown(
                f'<div class="panel"><b>One recommended action</b><br>'
                f"{result.message}</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<span class="source">{source_label(result)}</span>',
            unsafe_allow_html=True,
        )


def main() -> None:
    configure_page()
    render_header()

    top_left, top_right = st.columns([5, 1])
    top_left.caption("Private manager prototype · synthetic workplace support signals")
    if top_right.button("Reset demo", use_container_width=True):
        reset_demo()
        st.rerun()

    team_tab, private_tab = st.tabs(["Team Overview", "Private Review"])
    with team_tab:
        render_team_overview()
    with private_tab:
        input_column, result_column = st.columns([1.05, 0.95], gap="large")
        with input_column:
            signals = render_signal_form()
            if signals:
                st.session_state["assessment"] = assess_signals(signals)
                st.session_state.pop("bridge_result", None)
        with result_column:
            render_assessment()
        render_bridge_handoff()


if __name__ == "__main__":
    main()
