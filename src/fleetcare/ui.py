"""Two workspaces backed by authorized, fresh shared-store queries."""

import json
from datetime import datetime, timezone
import math
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from .config import DATA, ROOT, MODELS
from .detection import Baseline, evidence
from .service import Service, ConflictError
from .storage import StorageError
from .reporting import filter_faults, page_slice

LABELS = {
    "fault_id": "Fault ID",
    "vehicle_id": "Vehicle",
    "customer_id": "Customer ID",
    "customer_name": "Customer",
    "country": "Country",
    "city": "City",
    "fault_name": "Fault",
    "code": "Fault type",
    "severity": "Severity",
    "model_id": "Model",
    "started_at": "Abnormal start (UTC)",
    "confirmed_at": "Confirmed detection (UTC)",
    "ended_at": "Observed end (UTC)",
    "last_observed_at": "Last observation (UTC)",
    "creation_status": "Work order creation",
    "order_id": "Work order",
    "order_status": "Order status",
    "fault_status": "Fault status",
    "sensor_verification": "Sensor verification",
    "reported_resolution": "Reported resolution",
    "rating": "Rating",
    "notes": "Notes",
    "response_decision": "Customer decision",
    "finding": "Finding",
    "confirmed_cause": "Confirmed cause",
    "action": "Action",
    "actual_parts": "Actual reported parts",
    "rejection_reason": "Rejection reason",
    "response_at": "Response time (UTC)",
    "order_created_at": "Created (UTC)",
}
FINDINGS = {
    "unknown": "Unknown",
    "component_deterioration": "Component deterioration",
    "sensor_issue": "Sensor issue",
    "no_fault_found": "No fault found",
    "incorrect_recommendation": "Incorrect recommendation",
}
ACTIONS = {
    "report_only": "Report only",
    "inspection": "Inspection",
    "replacement": "Replacement",
    "connection_repair": "Connection repair",
}
UNITS = {
    "oil_temperature_c": "Oil temperature (°C)",
    "coolant_temperature_c": "Coolant temperature (°C)",
    "oil_pressure_bar": "Oil pressure (bar)",
    "charging_voltage_v": "Charging voltage (V)",
    "engine_vibration_rms": "Vibration (fictional relative units)",
}


def main():
    st.set_page_config(page_title="FleetCare · Predictive Maintenance", page_icon="⚙️", layout="wide")
    st.markdown(
        """<style>.block-container{padding-top:4.5rem;max-width:1600px}h1{letter-spacing:-1.2px}
    [data-testid="stMetric"]{background:#fff;border:1px solid #dce5ea;padding:12px;border-radius:8px}
    [data-testid="stSidebar"]{border-right:1px solid #dce5ea}.eyebrow{color:#147d92;font-size:12px;font-weight:700;letter-spacing:2px}</style>""",
        unsafe_allow_html=True,
    )
    if "service" not in st.session_state:
        try:
            try:
                cfg = dict(st.secrets["fleetcare"])
            except (KeyError, StreamlitSecretNotFoundError):
                cfg = {}
            st.session_state.service = Service(
                path=cfg.get("db_path"),
                auth_config=cfg.get("users"),
                database_url=cfg.get("database_url"),
                database_schema=cfg.get("database_schema"),
            )
        except (ValueError, OSError) as exc:
            st.error(f"Application configuration needs attention: {exc}")
            st.stop()
    svc = st.session_state.service
    token = st.session_state.get("token")
    if not token:
        sign_in(svc)
        return
    try:
        user = svc.principal(token)
    except PermissionError:
        st.session_state.pop("token", None)
        st.rerun()
    except StorageError as exc:
        st.error(str(exc))
        if st.button("Retry database connection"):
            st.rerun()
        return
    if st.session_state.get("workspace_next"):
        st.session_state.workspace = st.session_state.pop("workspace_next")
    with st.sidebar:
        st.markdown("### ⚙ FleetCare")
        st.caption("PREDICTIVE MAINTENANCE")
        st.write(user["display_name"])
        st.caption("Administrator" if user["role"] == "admin" else f"Customer · {user['customer_id']}")
        if user["role"] == "admin":
            workspace = st.radio("Workspace", ["Fault overview", "Work order overview"], key="workspace")
        else:
            workspace = "Work order overview"
            st.markdown("**Work order overview**")
        if st.button("Refresh saved changes", key="refresh"):
            st.rerun()
        if st.button("Sign out"):
            try:
                svc.logout(token)
            except StorageError as exc:
                st.error(str(exc))
                return
            svc.db.close()
            st.session_state.clear()
            st.rerun()
        st.divider()
        st.caption(
            "Independent synthetic portfolio demonstration by Enamul Haque. Fictional vehicles, procedures and parts."
        )
        st.caption(
            "Saved history uses PostgreSQL storage."
            if svc.backend == "postgresql"
            else "Local demo storage. Hosted history may be lost when the app restarts or is redeployed."
        )
        st.caption("Customer reports do not confirm sensor recovery.")
    st.markdown('<div class="eyebrow">FLEETCARE / PREDICTIVE MAINTENANCE</div>', unsafe_allow_html=True)
    try:
        if workspace == "Fault overview":
            if st.session_state.get("selected_fault"):
                fault_detail(svc, token, user)
            else:
                fault_overview(svc, token)
        else:
            if st.session_state.get("selected_order"):
                order_detail(svc, token, user)
            else:
                order_overview(svc, token, user)
    except (PermissionError, ValueError) as exc:
        st.error(str(exc))


def sign_in(svc):
    left, right = st.columns([1.3, 1])
    with left:
        st.markdown('<div class="eyebrow">FLEETCARE / PREDICTIVE MAINTENANCE</div>', unsafe_allow_html=True)
        st.title("Maintenance, connected.")
        st.write(
            "Review detected conditions, share clear work orders, and capture the customer’s response in one place."
        )
        st.caption("Independent synthetic portfolio demonstration · Enamul Haque")
    with right:
        st.subheader("Sign in")
        with st.form("sign_in"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submit = st.form_submit_button("Sign in", type="primary")
        if submit:
            try:
                st.session_state.token = svc.login(email, password)
                st.rerun()
            except (PermissionError, StorageError) as exc:
                st.error(str(exc))
        if svc.auth_mode == "public_demo":
            with st.expander("Local demo accounts"):
                st.write("Administrator: `admin@fleetcare.example` · `fleetcare-admin-demo`")
                st.write("Customer: `customer0000@fleetcare.example` · `fleetcare-customer-demo`")
                st.caption(
                    "Customer emails follow their four-digit customer ID. All demo credentials are intentionally public; use only synthetic data. Configure private credentials before restricting a hosted review."
                )


def display(frame, columns):
    return (
        frame.reindex(columns=columns)
        .rename(columns=LABELS)
        .astype(object)
        .where(pd.notna(frame.reindex(columns=columns).rename(columns=LABELS)), "")
    )


def choose_filter(label, column, frame, saved, prefix):
    canonical = {
        "creation_status": ["Not created", "Pending", "Created", "Failed"],
        "order_status": ["Open", "Completed", "Rejected"],
        "fault_status": ["Active", "Ended", "Unknown"],
    }
    options = ["All"] + canonical.get(column, sorted(frame[column].dropna().unique().tolist()))
    value = saved.get(column, "All")
    if value not in options:
        value = "All"
    return st.selectbox(label, options, index=options.index(value), key=f"{prefix}_{column}")


def fault_overview(svc, token):
    st.title("Fault overview")
    st.write("Validate a detected episode, review its evidence, and create a work order when appropriate.")
    frame = svc.faults(token)
    run = json.loads((DATA / "detection-run.json").read_text())
    st.caption(
        f"{run['processed_fleet']:,} vehicles processed · Oct–Dec 2025 · {run['telemetry_rows']:,} detailed observations · detection run {run['generated_at']} · UTC"
    )
    saved = st.session_state.get("fault_filters", {})
    filters = {}
    cols = st.columns([2, 1, 1, 1])
    filters["search"] = cols[0].text_input(
        "Search vehicle, customer, fault or order", value=saved.get("search", ""), key="fault_search"
    )
    with cols[1]:
        filters["country"] = choose_filter("Country", "country", frame, saved, "f")
    with cols[2]:
        filters["code"] = choose_filter("Fault type", "code", frame, saved, "f")
    with cols[3]:
        filters["creation_status"] = choose_filter("Order creation", "creation_status", frame, saved, "f")
    with st.expander("More filters and sorting"):
        columns = st.columns(4)
        for i, (label, column) in enumerate(
            [
                ("Vehicle", "vehicle_id"),
                ("Customer ID", "customer_id"),
                ("City", "city"),
                ("Model", "model_id"),
                ("Severity", "severity"),
                ("Fault status", "fault_status"),
                ("Work-order status", "order_status"),
            ]
        ):
            with columns[i % 4]:
                filters[column] = choose_filter(label, column, frame, saved, "f")
        dates = st.date_input(
            "Episode date range (UTC)",
            value=(
                pd.Timestamp(saved.get("date_from", "2025-10-01")).date(),
                pd.Timestamp(saved.get("date_to", "2025-12-31")).date(),
            ),
            key="fault_dates",
        )
        if len(dates) == 2:
            filters["date_from"], filters["date_to"] = [d.isoformat() for d in dates]
        options = ["Newest detection", "Oldest detection", "Severity", "Vehicle"]
        filters["sort"] = st.selectbox(
            "Sort", options, index=options.index(saved.get("sort", "Newest detection")), key="fault_sort"
        )
    if filters != saved:
        st.session_state.fault_page = 1
        st.session_state.fault_page_epoch = st.session_state.get("fault_page_epoch", 0) + 1
    st.session_state.fault_filters = filters
    filtered = filter_faults(frame, filters)
    cols = st.columns(3)
    cols[0].metric("Detected episodes", len(frame))
    cols[1].metric("Matching episodes", len(filtered))
    cols[2].metric("Awaiting order creation", int(filtered.creation_status.ne("Created").sum()))
    show = st.checkbox(
        "Show customer response columns",
        value=st.session_state.get("feedback_columns", False),
        key="feedback_columns_control",
    )
    st.session_state.feedback_columns = show
    st.download_button(
        "Download filtered joined results",
        filtered.to_csv(index=False).encode(),
        file_name="fleetcare-filtered-faults.csv",
        mime="text/csv",
    )
    if filtered.empty:
        st.info("No faults match these filters. Change the filters to explore the full result.")
    else:
        size = 25
        page = int(st.session_state.get("fault_page", 1))
        page = min(page, max(1, math.ceil(len(filtered) / size)))
        page = st.number_input(
            "Page",
            min_value=1,
            max_value=max(1, math.ceil(len(filtered) / size)),
            value=page,
            step=1,
            key=f"fault_page_control_{st.session_state.get('fault_page_epoch', 0)}",
        )
        st.session_state.fault_page = page
        visible, _, pages = page_slice(filtered, page, size)
        st.caption(
            f"{len(filtered):,} matching / {len(frame):,} total · page {page} of {pages}. Select a row to open its fault."
        )
        columns = [
            "vehicle_id",
            "customer_id",
            "customer_name",
            "country",
            "city",
            "fault_name",
            "severity",
            "started_at",
            "fault_status",
            "creation_status",
            "order_id",
            "order_status",
        ]
        if show:
            columns += [
                "response_decision",
                "finding",
                "confirmed_cause",
                "action",
                "actual_parts",
                "reported_resolution",
                "rating",
                "notes",
                "rejection_reason",
                "response_at",
            ]
        event = st.dataframe(
            display(visible, columns),
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key=f"fault_rows_{page}_{st.session_state.get('selection_epoch', 0)}",
        )
        if event.selection.rows:
            st.session_state.selected_fault = visible.iloc[event.selection.rows[0]].fault_id
            st.rerun()
    with st.expander("Detection run and audit · administrator"):
        report = json.loads((ROOT / "evaluation/report.json").read_text())
        st.write(
            f"Complete operational result: {run['fault_episodes']} episodes. Separate held-out evaluation: {report['events']} events, {report['operating_hours']:.2f} supported operating hours."
        )
        st.caption(
            "Evaluation and model cards document event matching, uncertainty and synthetic-only validity. No recovery is inferred from a customer decision."
        )
        st.dataframe(svc.audit(token).head(100), hide_index=True, width="stretch")
        legacy = svc.legacy_feedback(token)
        if not legacy.empty:
            st.write("Preserved legacy feedback history · no final customer decisions inferred")
            st.dataframe(legacy, hide_index=True, width="stretch")


def back(key, label):
    if st.button(label):
        st.session_state.pop(key, None)
        st.session_state.selection_epoch = st.session_state.get("selection_epoch", 0) + 1
        st.rerun()


def summary(f):
    st.subheader(f"{f['fault_name']} · {f['vehicle_id']}")
    st.write(
        f"**{f['customer_name']}** · {f['customer_id']} · {MODELS.get(f['model_id'], f['model_id'])} · {f['city']}, {f['country']}"
    )
    st.caption(
        f"{f['severity'].title()} severity · Fault: {f['fault_status']} · Sensor verification: {f['sensor_verification']}"
    )
    if f.get("legacy_state"):
        st.caption(
            f"Imported legacy state: {f['legacy_state']}. Original audit/history retained; missing response/end details are not fabricated."
        )


def fault_detail(svc, token, user):
    f = svc.fault(token, st.session_state.selected_fault)
    back("selected_fault", "← Back to faults")
    summary(f)
    if svc.auth_mode == "public_demo":
        st.caption(f"Assigned demo customer login: customer{f['customer_id'][-4:]}@fleetcare.example")
    if f["order_id"]:
        st.success(f"Created / exported · {f['order_id']} · {f['order_status']}")
        if st.button("Open work order", type="primary"):
            st.session_state.selected_order = f["order_id"]
            st.session_state.workspace_next = "Work order overview"
            st.rerun()
    else:
        if f["creation_status"] == "Failed":
            st.error("The last export failed. No work order was created. Retry this selected fault.")
        if st.button("Create work order", type="primary"):
            result = svc.create_order(token, f["fault_id"])
            if result["ok"]:
                st.session_state.flash = f"Created / exported · {result['order_id']}"
                st.rerun()
            else:
                st.error(result["error"])
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    snapshot = svc.order(token, f["order_id"])["snapshot"] if f["order_id"] else svc.snapshot(f)
    tabs = st.tabs(["Time series & evidence", "Recommended actions", "Parts list"])
    with tabs[0]:
        chart(svc, token, f, snapshot)
    with tabs[1]:
        actions(snapshot)
    with tabs[2]:
        proposed_parts(snapshot)
    if f["order_id"]:
        response = svc.order(token, f["order_id"])["response"]
        if response:
            st.subheader("Customer response")
            response_readback(response)


def actions(snapshot):
    st.subheader("Recommended actions")
    for i, task in enumerate(snapshot["actions"], 1):
        st.write(f"{i}. {task}")
    st.caption(
        f"Fictional procedures · {snapshot['playbook_id']} / {snapshot['playbook_version']}. This is a suspected condition, not a proven root cause."
    )


def proposed_parts(snapshot):
    st.subheader("Proposed parts")
    parts = pd.DataFrame(snapshot["parts"])
    if parts.empty:
        st.info("No compatible candidate parts were included in this saved recommendation.")
    else:
        st.dataframe(
            parts[["name", "sku", "quantity"]].rename(
                columns={"name": "Part", "sku": "Part ID", "quantity": "Proposed quantity"}
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "Conditional candidates. Findings determine actual replacement; all listed parts are not automatically required."
    )


def chart(svc, token, f, snapshot, order_id=None):
    data = svc.evidence(token, f["fault_id"], order_id)
    if data.empty:
        st.info(
            "Supporting observations are unavailable for this preserved legacy record. No replacement curve is invented."
        )
        return
    baseline = Baseline(DATA / "baseline.json")
    baseline.parameters = snapshot["baseline_parameters"]
    e = evidence(data, f["code"], baseline)
    sensor, kind, warn, crit, _, _, _ = snapshot["policy"]
    plot = pd.DataFrame(
        dict(
            timestamp=data.timestamp,
            observed=e.observed.where(data.quality_status.eq("valid")),
            expected=e.expected,
        )
    )
    for threshold, label in [(warn, "Warning boundary"), (crit, "Critical boundary")]:
        plot[label] = (
            e.expected - threshold
            if kind == "deficit"
            else e.expected * threshold
            if kind.startswith("ratio")
            else e.expected + threshold
        )
    # Insert explicit breaks at long gaps so the chart cannot bridge nights/missing coverage.
    extra = []
    for i in range(1, len(plot)):
        if (plot.timestamp.iloc[i] - plot.timestamp.iloc[i - 1]).total_seconds() > 600:
            extra.append({"timestamp": plot.timestamp.iloc[i - 1] + pd.Timedelta(minutes=5)})
    if extra:
        plot = pd.concat([plot, pd.DataFrame(extra)], ignore_index=True).sort_values("timestamp")
    fig = go.Figure()
    for column, color, dash in [
        ("observed", "#137e92", "solid"),
        ("expected", "#687d8b", "dash"),
        ("Warning boundary", "#c38431", "dot"),
        ("Critical boundary", "#b54f4b", "dot"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=plot.timestamp,
                y=plot[column],
                name={"observed": "Observed", "expected": "Expected healthy baseline"}.get(column, column),
                line=dict(color=color, dash=dash),
                connectgaps=False,
            )
        )
    end = f["ended_at"] or f["last_observed_at"]
    fig.add_vrect(x0=f["started_at"], x1=end, fillcolor="#df8d6e", opacity=0.13, line_width=0)
    fig.add_vline(
        x=pd.Timestamp(f["confirmed_at"]).timestamp() * 1000, line_color="#b54f4b", line_dash="dash"
    )
    if f["ended_at"]:
        fig.add_vline(x=pd.Timestamp(f["ended_at"]).timestamp() * 1000, line_color="#147d92", line_dash="dot")
    fig.update_layout(
        height=390,
        yaxis_title=UNITS[sensor],
        xaxis_title="Observation time (UTC)",
        margin=dict(t=45, l=0, r=0, b=0),
        legend=dict(orientation="h", y=1.16),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.write(
        f"**First unusual readings:** {readable_time(f['started_at'])} · "
        f"**Alert confirmed:** {readable_time(f['confirmed_at'])}"
    )
    if f["ended_at"]:
        st.write(
            f"**Last abnormal reading:** {readable_time(f['ended_at'])} · "
            f"**Return to normal confirmed:** {readable_time(f['recovery_confirmed_at'])}"
        )
    else:
        st.write("**Return to normal: not confirmed in the recorded readings.**")
        st.caption(
            "The available sensor data does not show a sustained return to normal. "
            "Completing a work order saves the customer’s report; it does not confirm recovery from sensor data."
        )
    proof = json.loads(f["evidence"])
    st.write(customer_trigger(f["code"], proof))
    st.caption(f"Latest available sensor reading: {readable_time(f['last_observed_at'])}.")
    if order_id:
        st.caption(
            f"This order’s recommendation used readings available through {readable_time(snapshot['evidence_as_of'])}."
        )
    if f["last_observed_at"] > snapshot["evidence_as_of"]:
        st.info("New sensor readings are available since this order’s recommendation was saved.")
    with st.expander("How this alert was detected"):
        st.write(
            f"At confirmation: {proof.get('observed', 0):.2f} observed versus "
            f"{proof.get('expected', 0):.2f} expected; {proof.get('comparison', kind)} "
            f"{proof.get('value', 0):.2f}, threshold {proof.get('threshold', '—')} "
            f"across {proof.get('window_minutes', '—')} minutes. "
            "Readings are taken every five minutes. At least 80% of expected readings must be usable; "
            "startup and unsuitable operating conditions are excluded. Thresholds are fictional demo settings."
        )
        st.caption(
            "The expected value accounts for operating conditions. This alert identifies an unusual "
            "sensor condition, not a confirmed mechanical cause."
        )


def readable_time(value):
    return pd.Timestamp(value).tz_convert("UTC").strftime("%d %b %Y at %H:%M UTC")


def customer_trigger(code, proof):
    labels = {
        "FC-01": ("Oil temperature", "°C", "higher than expected"),
        "FC-02": ("Coolant temperature", "°C", "higher than expected"),
        "FC-03": ("Oil pressure", " bar", "lower than expected"),
        "FC-04": ("Charging voltage", " V", "lower than expected"),
        "FC-05": ("Engine vibration", " relative units", "higher than expected"),
    }
    label, unit, direction = labels[code]
    return (
        f"**Why this alert appeared:** {label} stayed {direction} for at least "
        f"{proof.get('window_minutes', '—')} minutes. "
        f"When the alert was confirmed, the reading was {proof.get('observed', 0):.1f}{unit}; "
        f"the expected value for those operating conditions was {proof.get('expected', 0):.1f}{unit}."
    )


def order_overview(svc, token, user):
    st.title("Work order overview")
    st.write("Review assigned maintenance recommendations and submit a final response.")
    frame = svc.orders(token)
    counts = frame.order_status.value_counts()
    st.caption(
        f"Saved orders · Open: {counts.get('Open', 0)} · Completed: {counts.get('Completed', 0)} · "
        f"Rejected: {counts.get('Rejected', 0)}. Signing out does not delete saved orders or responses."
    )
    if st.session_state.pop("show_order_history", False):
        st.session_state.order_status_filter = "All"
        st.session_state.order_search = ""
        st.session_state.pop("order_page_control", None)
        st.session_state.order_filters = dict(status="All", search="")
    c = st.columns([1, 2])
    saved = st.session_state.get("order_filters", {})
    if "order_status_filter" not in st.session_state:
        st.session_state.order_status_filter = saved.get("status", "Open")
    status = c[0].selectbox(
        "Order status",
        ["Open", "Completed", "Rejected", "All"],
        key="order_status_filter",
    )
    if status == "Open" and counts.get("Completed", 0) + counts.get("Rejected", 0):
        st.info("Completed and rejected orders are saved in history. The Open filter hides them.")
        st.button(
            "View all saved orders",
            on_click=lambda: st.session_state.update(show_order_history=True),
        )
    search = c[1].text_input("Search order or vehicle", value=saved.get("search", ""), key="order_search")
    st.session_state.order_filters = dict(status=status, search=search)
    filtered = frame if status == "All" else frame[frame.order_status == status]
    if search.strip():
        text = (
            filtered[["order_id", "vehicle_id", "fault_name", "customer_name"]]
            .fillna("")
            .agg(" ".join, axis=1)
        )
        filtered = filtered[text.str.contains(search.strip(), case=False, regex=False)]
    st.caption(
        f"{len(filtered)} matching / {len(frame)} assigned orders. Select a row to open its actions, proposed parts and response."
    )
    if filtered.empty:
        st.info(
            "No orders match this selection. Newly saved orders and responses appear after Refresh saved changes."
        )
        return
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=max(1, math.ceil(len(filtered) / 25)),
        value=1,
        step=1,
        key="order_page_control",
    )
    visible, _, _ = page_slice(filtered, page, 25)
    event = st.dataframe(
        display(
            visible,
            [
                "order_id",
                "vehicle_id",
                "fault_name",
                "severity",
                "country",
                "city",
                "order_created_at",
                "order_status",
            ],
        ),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"order_rows_{page}_{st.session_state.get('selection_epoch', 0)}",
    )
    if event.selection.rows:
        st.session_state.selected_order = visible.iloc[event.selection.rows[0]].order_id
        st.rerun()


def order_detail(svc, token, user):
    order = svc.order(token, st.session_state.selected_order)
    back("selected_order", "← Back to work orders")
    st.title(order["order_id"])
    summary(order["fault"])
    st.write(f"**{order['status']}** · Created {order['created_at']} (UTC)")
    tabs = st.tabs(["Actions & proposed parts", "Time series & evidence"])
    with tabs[0]:
        actions(order["snapshot"])
        proposed_parts(order["snapshot"])
    with tabs[1]:
        chart(svc, token, order["fault"], order["snapshot"], order["order_id"])
    st.subheader("Customer response")
    if order["response"]:
        response_readback(order["response"])
    elif order["status"] != "Open":
        st.info(
            "Legacy terminal order. Its original history is preserved; no final customer response is invented."
        )
    elif user["role"] == "customer":
        response_form(svc, token, order)
    else:
        st.info(
            "Awaiting a response from the assigned customer. Administrators can inspect but cannot impersonate a customer response."
        )


def response_readback(response):
    st.write(f"**Decision: {response['decision']}** · Response time: {response['response_at']} (UTC)")
    if response["decision"] == "Rejected":
        st.write("**Rejection reason:** " + response["rejection_reason"])
    else:
        st.write(
            f"Finding: {FINDINGS.get(response['finding'], response['finding'])} · Confirmed cause: {str(response['confirmed_cause']).replace('-', ' ').title()} · Action: {ACTIONS.get(response['action'], response['action'])}"
        )
        st.write("Reported resolution: " + response["reported_resolution"])
        parts = json.loads(response["actual_parts"] or "{}")
        if parts:
            st.dataframe(
                pd.DataFrame([{"Actual reported part": k, "Quantity": v} for k, v in parts.items()]),
                hide_index=True,
            )
    st.write(
        "Rating: " + (str(response["rating"]) + " / 5" if response["rating"] is not None else "Not rated")
    )
    if response["notes"]:
        st.write("Notes: " + response["notes"])
    st.caption(
        "A customer-reported outcome is separate from evidence-derived fault status and sensor verification."
    )


def response_form(svc, token, order):
    decision = st.radio(
        "Decision",
        ["Completed", "Rejected"],
        index=None,
        horizontal=True,
        key="response_decision_" + order["order_id"],
    )
    action = "report_only"
    if decision == "Completed":
        allowed = ["report_only", "inspection", "replacement"] + (
            ["connection_repair"] if order["fault"]["code"] == "FC-04" else []
        )
        action = st.selectbox(
            "Action performed",
            allowed,
            format_func=lambda x: ACTIONS[x],
            key="response_action_" + order["order_id"],
        )
    with st.form("customer_response"):
        finding, cause, resolution = "unknown", "unknown", "Not sure"
        parts = {}
        reason = ""
        if decision == "Completed":
            finding = st.selectbox("Finding", list(FINDINGS), format_func=lambda x: FINDINGS[x])
            cause = st.selectbox(
                "Confirmed cause",
                ["unknown"] + [p["family"] for p in order["snapshot"]["parts"]],
                format_func=lambda x: x.replace("-", " ").title(),
            )
            if action == "replacement":
                proposals = {p["sku"]: p for p in order["snapshot"]["parts"]}
                actual = st.multiselect(
                    "Actual compatible parts",
                    list(proposals),
                    format_func=lambda x: f"{proposals[x]['name']} · {x}",
                )
                for sku in actual:
                    parts[sku] = st.number_input(
                        f"Quantity · {sku}",
                        min_value=1,
                        max_value=proposals[sku]["quantity"],
                        value=1,
                        step=1,
                    )
            resolution = st.selectbox("Reported resolution", ["Not sure", "Resolved", "Not resolved"])
        elif decision == "Rejected":
            reason = st.text_area("Rejection reason (required)")
        c = st.columns(3)
        day = c[0].date_input("Response date (UTC)", value=datetime.now(timezone.utc).date())
        time = c[1].time_input(
            "Response time (UTC)",
            value=datetime.now(timezone.utc).time().replace(second=0, microsecond=0, tzinfo=None),
        )
        rating = c[2].selectbox("Rating (optional)", ["Not rated", 1, 2, 3, 4, 5])
        notes = st.text_area("Notes (optional)", max_chars=4000)
        submitted = st.form_submit_button("Submit response", type="primary", disabled=decision is None)
    if submitted:
        payload = dict(
            decision=decision,
            finding=finding,
            confirmed_cause=cause,
            action=action,
            actual_parts=parts,
            reported_resolution=resolution,
            rejection_reason=reason,
            rating=None if rating == "Not rated" else rating,
            notes=notes,
            response_at=datetime.combine(day, time, tzinfo=timezone.utc).isoformat(),
        )
        try:
            svc.respond(token, order["order_id"], payload)
            st.success("Response saved. The administrator’s fault row now includes your response.")
            st.rerun()
        except (ValueError, ConflictError) as exc:
            st.error(str(exc))
