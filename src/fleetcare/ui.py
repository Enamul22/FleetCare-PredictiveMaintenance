"""Operational UI. Evaluation truth and offline training modules are never imported here."""

import json
import os
import uuid
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from .config import DATA, ROOT, MODELS, FAULTS, FAMILIES, TASKS, POLICY, BASELINE
from .ingestion import Sources, candidates
from .detection import evidence
from .service import Service

VIEWS = [
    "Fleet overview",
    "Asset investigation",
    "Incidents & work orders",
    "Technician feedback",
    "Evaluation & audit",
]
SCENARIOS = [
    "FC-01",
    "FC-02",
    "FC-03",
    "FC-04",
    "FC-05",
    "healthy_high_load",
    "sensor_quality",
    "missing_data",
    "multi_fault",
]


@st.cache_data
def immutable_tables():
    return (
        Sources().crm(),
        pd.read_parquet(DATA / "monthly.parquet"),
        pd.read_parquet(DATA / "daily.parquet"),
    )


def main():
    st.set_page_config(page_title="FleetCare · Maintenance operations", page_icon="⚙️", layout="wide")
    st.markdown(
        """<style>
    .block-container{padding-top:4.5rem;max-width:1500px} h1{letter-spacing:-1.4px} h2,h3{letter-spacing:-.4px}
    [data-testid="stMetric"]{background:white;border:1px solid #d8e3e9;border-radius:10px;padding:18px}
    [data-testid="stSidebar"]{border-right:1px solid #d8e3e9}
    .eyebrow{color:#147d92;font-weight:700;letter-spacing:2px;font-size:12px}
    </style>""",
        unsafe_allow_html=True,
    )
    if "service" not in st.session_state:
        mode = os.environ.get("FLEETCARE_MODE", "session")
        if mode not in ("session", "local"):
            st.error("FLEETCARE_MODE must be session or local")
            st.stop()
        path = (
            os.environ.get("FLEETCARE_DB", str(ROOT / "fleetcare.sqlite")) if mode == "local" else ":memory:"
        )
        st.session_state.service = Service(path)
        st.session_state.mode = mode
    svc = st.session_state.service
    assets, monthly, daily = immutable_tables()
    with st.sidebar:
        st.markdown("### ⚙ FleetCare")
        st.caption("MAINTENANCE OPERATIONS")
        view = st.radio("Workspace", VIEWS, key="view")
        st.divider()
        st.caption("SYNTHETIC PORTFOLIO DEMO · ENAMUL HAQUE")
        st.write(
            "Local persistent state"
            if st.session_state.mode == "local"
            else "Private session · temporary changes"
        )
        if st.session_state.mode == "session" and st.button("Reset demo", key="reset"):
            svc.db.close()
            st.session_state.clear()
            st.rerun()
        st.caption(
            "Fictional fleet, parts, prices and procedures. Independent project; no employer affiliation."
        )
    st.markdown('<div class="eyebrow">FLEETCARE / PREDICTIVE MAINTENANCE</div>', unsafe_allow_html=True)
    st.title(view)
    if view == "Fleet overview":
        overview(svc, assets, monthly)
    elif view == "Asset investigation":
        investigation(svc, assets, daily)
    elif view == "Incidents & work orders":
        orders(svc, assets)
    elif view == "Technician feedback":
        feedback(svc, assets)
    else:
        audit(svc)


def overview(svc, assets, monthly):
    st.write("Prioritize abnormal conditions, investigate evidence, and verify maintenance outcomes.")
    c = st.columns(4)
    model = c[0].selectbox("Model", ["All"] + list(MODELS), format_func=lambda x: MODELS.get(x, x))
    country = c[1].selectbox("Country", ["All"] + sorted(assets.country.unique()))
    month = c[2].selectbox("Month", sorted(monthly.month.unique(), reverse=True))
    severity = c[3].selectbox("Severity", ["All", "critical", "warning"])
    a = assets.copy()
    if model != "All":
        a = a[a.model_id == model]
    if country != "All":
        a = a[a.country == country]
    m = monthly[(monthly.month == month) & monthly.vehicle_id.isin(a.vehicle_id)]
    inc = svc.table("incidents")
    inc = inc[inc.vehicle_id.isin(a.vehicle_id) & inc.started.str.startswith(month)]
    if severity != "All":
        inc = inc[inc.severity == severity]
    cols = st.columns(4)
    for col, label, value in zip(
        cols,
        ["Vehicles in scope", "Operating hours", "Active incidents", "Sensor-verified resolutions"],
        [
            len(a),
            f"{m.operating_hours.sum():,.0f}",
            int((inc.state != "resolved").sum()),
            int((inc.state == "resolved").sum()),
        ],
    ):
        col.metric(label, value)
    left, right = st.columns([1.5, 1])
    with left:
        st.subheader("Usage across the fleet")
        chart = (
            m.merge(a[["vehicle_id", "model_id"]], on="vehicle_id")
            .groupby("model_id", as_index=False)
            .operating_hours.sum()
        )
        chart["model"] = chart.model_id.map(MODELS)
        fig = px.bar(
            chart,
            x="model",
            y="operating_hours",
            color_discrete_sequence=["#147d92"],
            labels={"operating_hours": "Operating hours", "model": ""},
        )
        fig.update_layout(margin=dict(t=15, l=0, r=0, b=0), height=300)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Start a guided demonstration")
        st.write(
            "1. Open Asset investigation and advance a staged fault.\n\n2. Assign and start its mock work order.\n\n3. Record a finding and action, then advance telemetry to verify the outcome."
        )
        st.info(
            "Try FC-01 for a successful repair, FC-02 for a stockout, and an inspect-only action for an ineffective repair."
        )
    st.subheader("Operational queue")
    if inc.empty:
        st.info(
            "No incidents in this selection. Advance a replay in Asset investigation to populate the queue."
        )
    else:
        st.dataframe(
            inc[["vehicle_id", "code", "severity", "state", "started"]], hide_index=True, width="stretch"
        )
    st.caption(
        "Daily history: Jan–Dec 2025, all 1,000 vehicles. Detailed telemetry: nine staged windows on 15 Dec, 5-minute samples. Overview incident counts reflect replayed state, not whole-fleet fault prevalence."
    )
    st.dataframe(
        a[["vehicle_id", "model_id", "country", "age_years", "usage_profile"]].head(100),
        hide_index=True,
        width="stretch",
    )


def investigation(svc, assets, daily):
    source = st.radio("Investigation source", ["Guided replay", "Fleet history"], horizontal=True)
    if source == "Fleet history":
        vehicle = st.selectbox("Asset", assets.vehicle_id)
        a = assets[assets.vehicle_id == vehicle].iloc[0]
        st.write(f"**{vehicle} · {MODELS[a.model_id]} · {a.country}**")
        history = daily[daily.vehicle_id == vehicle].copy()
        month = st.selectbox(
            "History month", sorted(history.date.dt.strftime("%Y-%m").unique(), reverse=True)
        )
        history = history[history.date.dt.strftime("%Y-%m") == month]
        fig = px.line(
            history,
            x="date",
            y="operating_hours",
            labels={"date": "UTC day", "operating_hours": "Operating hours"},
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(history, hide_index=True, width="stretch")
        service_history = pd.read_parquet(DATA / "service_history.parquet")
        st.dataframe(service_history[service_history.vehicle_id == vehicle], hide_index=True, width="stretch")
        st.info(
            "Daily history is available for every asset. The compact package includes detailed sensor history only for the labelled guided replays."
        )
        return
    st.caption("Staged demonstration scenarios are separate from the held-out evaluation cohort.")
    scenario = st.selectbox("Replay scenario", SCENARIOS, key="scenario")
    f = svc.replay_frame(scenario)
    vehicle = f.vehicle_id.iloc[0]
    a = assets[assets.vehicle_id == vehicle].iloc[0]
    st.write(f"**{vehicle}** · {MODELS[a.model_id]} · {a.country} · {a.age_years:g} years")
    row = svc.db.execute("select cursor from replay where scenario=?", (scenario,)).fetchone()
    cursor = row[0] if row else 0
    c = st.columns([1, 1, 2])
    steps = c[0].selectbox("Advance by", [3, 6, 12], format_func=lambda x: f"{x * 5} minutes")
    fail = c[1].checkbox("Simulate export interruption")
    if c[2].button("Advance replay", type="primary"):
        svc.advance(scenario, steps, fail)
        st.rerun()
    st.progress(cursor / len(f), text=f"{cursor} / {len(f)} samples ingested · 5-minute operating cadence")
    if cursor == 0:
        st.info(
            "Advance the replay to inspect observed evidence. Future readings are hidden until replay reaches them."
        )
        return
    seen = f.iloc[:cursor]
    quality = seen.quality_status.iloc[-1]
    if quality != "valid":
        st.warning(
            f"Latest telemetry quality: {quality}. Condition is unknown; invalid samples cannot establish recovery."
        )
    code = st.selectbox(
        "Evidence channel",
        list(FAULTS),
        format_func=lambda x: f"{x} · {FAULTS[x][-1]}",
        index=list(FAULTS).index(scenario) if scenario in FAULTS else 0,
    )
    e = evidence(seen, code)
    from .detection import classify

    status, _ = classify(seen, code, svc.baseline)
    st.write(f"**Evidence status: {status}** · {FAULTS[code][-1]}")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=seen.timestamp,
            y=e.observed,
            name="Observed",
            line=dict(color="#147d92", width=3),
            connectgaps=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=seen.timestamp,
            y=e.expected,
            name="Expected healthy baseline",
            line=dict(color="#607D8B", dash="dash"),
        )
    )
    sensor, kind, warn, _, _, _, _ = FAULTS[code]
    boundary = (
        e.expected - warn
        if kind == "deficit"
        else e.expected * warn
        if kind.startswith("ratio")
        else e.expected + warn
    )
    fig.add_trace(
        go.Scatter(
            x=seen.timestamp, y=boundary, name="Warning boundary", line=dict(color="#b96b20", dash="dot")
        )
    )
    inc = svc.table("incidents")
    for i in inc[inc.vehicle_id == vehicle].itertuples():
        fig.add_vline(x=pd.Timestamp(i.started).timestamp() * 1000, line_color="#b13d38", line_dash="dot")
    fig.update_layout(
        yaxis_title=sensor.replace("_", " "),
        xaxis_title="Event time (UTC)",
        height=370,
        legend=dict(orientation="h", y=1.15),
        margin=dict(t=45, b=0, l=0, r=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    c = st.columns(3)
    c[0].metric("Valid eligible samples", f"{int(e.valid.sum())} / {len(e)}")
    c[1].metric("Lifetime engine hours", f"{seen.lifetime_engine_hours.iloc[-1]:,.1f}")
    c[2].metric("Odometer (km)", f"{seen.odometer_km.iloc[-1]:,.0f}")
    st.caption(
        "Thresholds are fictional policy parameters. Five-minute samples bound timing precision; single samples cannot establish persistence. Missing or ineligible data implies unknown condition."
    )
    with st.expander("Measurements and comparison evidence"):
        st.dataframe(e, hide_index=True, width="stretch")
    st.subheader("Component and service history")
    st.dataframe(svc.table("components").query("vehicle_id == @vehicle"), hide_index=True, width="stretch")
    history = pd.read_parquet(DATA / "service_history.parquet")
    st.dataframe(history[history.vehicle_id == vehicle], hide_index=True, width="stretch")
    own_orders = svc.table("orders").merge(
        inc[inc.vehicle_id == vehicle][["id"]],
        left_on="incident_id",
        right_on="id",
        suffixes=("", "_incident"),
    )
    feedback_rows = svc.table("feedback")
    st.dataframe(feedback_rows[feedback_rows.order_id.isin(own_orders.id)], hide_index=True, width="stretch")
    with st.expander("Daily operating history · all periods"):
        st.dataframe(daily[daily.vehicle_id == vehicle], hide_index=True, width="stretch")


def orders(svc, assets):
    o = svc.table("orders")
    st.caption(
        "Work orders are automatically exported to a mock service system after persistent evidence. All actions stay within this demo."
    )
    if st.button("Retry pending exports"):
        svc.export()
        st.rerun()
    with st.expander("Export delivery and retries"):
        st.dataframe(svc.table("outbox"), hide_index=True, width="stretch")
    if o.empty:
        st.info("No exported orders yet. Advance an incident replay, or retry pending exports.")
        return
    st.dataframe(o, hide_index=True, width="stretch")
    oid = st.selectbox("Work order", o.id, key="order")
    ctx = svc.order_context(oid)
    a = assets[assets.vehicle_id == ctx["vehicle_id"]].iloc[0]
    st.subheader(f"{ctx['code']} · {FAULTS[ctx['code']][-1]}")
    st.write(
        f"**{ctx['severity'].upper()} · {ctx['state']}** | Vehicle {ctx['vehicle_id']} | Customer {a.customer_id}"
    )
    st.write(TASKS[ctx["code"]])
    proof = json.loads(ctx["evidence"])
    st.write(
        f"Trigger: measured **{proof['observed']:.2f}**, expected **{proof['expected']:.2f}**, comparison **{proof['value']:.2f}** at {proof['timestamp']}."
    )
    st.write(
        f"{proof.get('sensor', FAULTS[ctx['code']][0])}: {proof.get('valid_samples', '—')} valid samples across {proof.get('window_minutes', '—')} minutes; {proof.get('comparison', '')} threshold {proof.get('threshold', '—')}."
    )
    st.caption(
        f"Suspected condition; root cause requires investigation. {ctx['policy_version']} · {ctx['baseline_version']} · {ctx['playbook_version']}"
    )
    for state, label in [
        ("assigned", "Assign order"),
        ("in_progress", "Start work"),
        ("cancelled", "Cancel order"),
    ]:
        allowed = {
            "created": ["assigned", "cancelled"],
            "assigned": ["in_progress", "cancelled"],
            "in_progress": ["cancelled"],
        }
        if state in allowed.get(ctx["order_state"], []) and st.button(label, key=state):
            svc.transition(oid, state)
            st.rerun()
    st.subheader("Compatible candidate parts")
    parts = candidates(ctx["code"], a.model_id, ctx["code"]).merge(svc.table("inventory"), on="sku")
    st.dataframe(
        parts[["sku", "family", "available", "reserved", "unit_price_eur", "currency", "supplier"]],
        hide_index=True,
        width="stretch",
    )
    st.caption("Candidates only. Findings determine actual consumption; stockouts remain visible.")
    if ctx["order_state"] not in ("completed", "cancelled"):
        sku = st.selectbox("Candidate to reserve", parts.sku)
        if st.button("Receive one unit · mock ERP delivery"):
            svc.receive_delivery(str(uuid.uuid4()), sku, 1)
            st.success("Fictional ERP delivery received; reserve the unit to resume work.")
        if st.button("Reserve one candidate"):
            if svc.reserve(oid, sku):
                st.success("One unit reserved. Repeating this action has no duplicate effect.")
            else:
                st.warning("Unavailable · waiting for parts. No incompatible substitution was made.")
    st.dataframe(svc.table("lines").query("order_id == @oid"), hide_index=True, width="stretch")


def feedback(svc, assets):
    o = svc.table("orders")
    o = o[o.state == "in_progress"]
    st.write(
        "Capture workshop findings and actual actions. Completion starts verification; the incident remains open until subsequent evidence supports recovery."
    )
    if o.empty:
        st.info(
            "Assign and start a work order first. Completed feedback remains visible in Evaluation & audit."
        )
        return
    oid = st.selectbox("Order in progress", o.id, key="feedback_order")
    ctx = svc.order_context(oid)
    a = assets[assets.vehicle_id == ctx["vehicle_id"]].iloc[0]
    st.write(f"**{ctx['vehicle_id']} · {ctx['code']} · {FAULTS[ctx['code']][-1]}**")
    with st.form("feedback"):
        role = st.selectbox("Reporting role", ["technician", "customer"])
        finding = st.selectbox(
            "Finding",
            [
                "component_deterioration",
                "sensor_bias",
                "no_fault_found",
                "incorrect_recommendation",
                "unknown",
            ],
        )
        cause = st.selectbox("Confirmed cause", ["unknown"] + FAMILIES[ctx["code"]])
        action = st.selectbox("Action", ["replace", "inspect_only", "connection_repair", "report_only"])
        p = candidates(ctx["code"], a.model_id, ctx["code"])
        parts = st.multiselect("Actual parts · quantity 1 each", p.sku)
        outcome = st.selectbox("Reported resolution", ["unknown", "resolved", "not_resolved"])
        notes = st.text_area(
            "Notes",
            help="Demo setting: include “partial” for a partial effect when the correct component is repaired.",
        )
        submitted = st.form_submit_button("Record feedback", type="primary")
    st.caption(
        "Staged mechanical causes use the first compatible family in each playbook. Inspect-only or replacing another cause demonstrates ineffective repair. No synthetic outcome proves real-world effectiveness."
    )
    if submitted:
        try:
            if parts and role == "technician":
                # Reservation attempts remain explicit. Completion transaction checks every chosen part.
                for sku in parts:
                    svc.reserve(oid, sku)
            effect = svc.feedback(
                str(uuid.uuid4()),
                oid,
                role,
                finding,
                cause,
                action,
                {s: 1 for s in parts},
                outcome,
                notes,
            )
            st.success("Feedback recorded. Advance the same replay to inspect subsequent verification.")
            st.caption(
                f"Synthetic branch setting: {effect:.0%} repair effect. Offline evaluation is unchanged."
            )
        except ValueError as err:
            st.error(str(err))


def audit(svc):
    st.write("Held-out synthetic performance, delivery history, and traceable operational decisions.")
    report = json.loads((ROOT / "evaluation/report.json").read_text())
    rows = []
    for name, m in report["methods"].items():
        rows.append(
            dict(
                method=name,
                detected=f"{m['detected_events']} / {m['total_events']}",
                recall=f"{m['event_recall']:.1%}",
                false_incidents=m["false_incidents"],
                false_per_100h=round(m["false_incidents_per_100_hours"], 2),
                delay_min=m["median_detection_delay_minutes"],
            )
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        f"{report['heldout_vehicles']} held-out vehicles · {report['operating_hours']:.1f} operating hours · {report['events']} injected events · curated replays excluded."
    )
    st.info(report["challenger_decision"])
    with st.expander("Fault-family recall, denominators and uncertainty"):
        st.json(report["methods"]["rules"])
        st.write(report["event_matching"])
    st.warning(
        "Synthetic validity only. Some mild or gradual conditions remain undetected. Abnormal-condition detection is not a general guarantee of warning before failure."
    )
    tab1, tab2, tab3 = st.tabs(["Operational audit", "Feedback & verification", "Data lineage"])
    with tab1:
        st.dataframe(svc.table("audit").iloc[::-1], hide_index=True, width="stretch")
    with tab2:
        st.dataframe(svc.table("feedback"), hide_index=True, width="stretch")
        st.dataframe(svc.table("incidents"), hide_index=True, width="stretch")
    with tab3:
        st.write(f"Policy {POLICY} · baseline {BASELINE} · playbooks PB-1.0")
        st.json(json.loads((DATA / "manifest.json").read_text()))
        st.caption(
            "CRM / ERP / telemetry are fictional exports joined by canonical asset mapping. Hidden simulator truth is stored offline in evaluation/truth.json and never queried by application inference."
        )
