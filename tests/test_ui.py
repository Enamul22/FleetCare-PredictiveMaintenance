from streamlit.testing.v1 import AppTest


def login(app, email, password):
    app.text_input(key="login_email").input(email)
    app.text_input(key="login_password").input(password)
    next(b for b in app.button if b.label == "Sign in").click().run()
    assert not app.exception
    return app


def test_two_workspaces_and_complete_cross_session_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEETCARE_DB", str(tmp_path / "shared.sqlite"))
    admin = login(
        AppTest.from_file("app.py", default_timeout=30).run(),
        "admin@fleetcare.example",
        "fleetcare-admin-demo",
    )
    assert admin.title[0].value == "Fault overview"
    assert len(admin.radio(key="workspace").options) == 2
    svc = admin.session_state["service"]
    token = admin.session_state["token"]
    rows = svc.faults(token)
    assert int(admin.metric[0].value) == len(rows)
    # Native row-selection events are verified in the browser; AppTest exercises the selected route.
    selected = rows.iloc[0]
    admin.session_state["selected_fault"] = selected.fault_id
    admin.run()
    assert [t.label for t in admin.tabs] == ["Time series & evidence", "Recommended actions", "Parts list"]
    next(b for b in admin.button if b.label == "Create work order").click().run()
    assert not admin.exception
    oid = svc.fault(token, selected.fault_id)["order_id"]
    assert oid
    next(b for b in admin.button if b.label == "Open work order").click().run()
    assert not admin.exception
    customer = login(
        AppTest.from_file("app.py", default_timeout=30).run(),
        f"customer{selected.customer_id[-4:]}@fleetcare.example",
        "fleetcare-customer-demo",
    )
    assert customer.title[0].value == "Work order overview"
    assert not any(r.label == "Workspace" for r in customer.radio)
    customer.session_state["selected_order"] = oid
    customer.run()
    customer.radio(key="response_decision_" + oid).set_value("Completed").run()
    next(s for s in customer.selectbox if s.label == "Reported resolution").select("Not resolved")
    next(s for s in customer.selectbox if s.label == "Rating (optional)").select(4)
    next(s for s in customer.text_area if s.label == "Notes (optional)").input(
        "partial is only customer feedback"
    )
    next(b for b in customer.button if b.label == "Submit response").click().run()
    assert not customer.exception
    assert any("Decision: Completed" in m.value for m in customer.markdown)
    admin.session_state["selected_order"] = None
    admin.session_state["workspace"] = "Fault overview"
    admin.session_state["selected_fault"] = selected.fault_id
    admin.run()
    assert not admin.exception
    row = svc.fault(token, selected.fault_id)
    assert row["reported_resolution"] == "Not resolved" and row["rating"] == 4
    assert (
        row["notes"] == "partial is only customer feedback" and row["fault_status"] == selected.fault_status
    )


def test_rejection_and_null_feedback_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEETCARE_DB", str(tmp_path / "reject.sqlite"))
    admin = login(
        AppTest.from_file("app.py", default_timeout=30).run(),
        "admin@fleetcare.example",
        "fleetcare-admin-demo",
    )
    svc = admin.session_state["service"]
    a = admin.session_state["token"]
    f = svc.faults(a).iloc[0]
    oid = svc.create_order(a, f.fault_id)["order_id"]
    customer = login(
        AppTest.from_file("app.py", default_timeout=30).run(),
        f"customer{f.customer_id[-4:]}@fleetcare.example",
        "fleetcare-customer-demo",
    )
    customer.session_state["selected_order"] = oid
    customer.run()
    assert customer.radio(key="response_decision_" + oid).value is None
    customer.radio(key="response_decision_" + oid).set_value("Rejected").run()
    assert not any(s.label == "Finding" for s in customer.selectbox)
    next(b for b in customer.button if b.label == "Submit response").click().run()
    assert any("rejection reason" in e.value for e in customer.error)
    next(t for t in customer.text_area if t.label == "Rejection reason (required)").input(
        "Please verify the recommendation"
    )
    next(b for b in customer.button if b.label == "Submit response").click().run()
    assert not customer.exception
    row = svc.fault(a, f.fault_id)
    assert row["order_status"] == "Rejected" and row["reported_resolution"] is None and row["rating"] is None
