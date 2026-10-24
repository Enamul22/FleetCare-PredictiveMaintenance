from streamlit.testing.v1 import AppTest


def test_all_views_and_empty_states(monkeypatch):
    monkeypatch.setenv("FLEETCARE_MODE", "session")
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    for view in [
        "Asset investigation",
        "Incidents & work orders",
        "Technician feedback",
        "Evaluation & audit",
        "Fleet overview",
    ]:
        app.radio(key="view").set_value(view).run()
        assert not app.exception
    app.selectbox[0].select("ALD").run()
    assert not app.exception
    assert app.metric[0].value == "250"


def test_ui_repair_path(monkeypatch):
    monkeypatch.setenv("FLEETCARE_MODE", "session")
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.radio(key="view").set_value("Asset investigation").run()
    app.selectbox[1].select(12).run()
    next(b for b in app.button if b.label == "Advance replay").click().run()
    assert not app.exception
    app.radio(key="view").set_value("Incidents & work orders").run()
    next(b for b in app.button if b.label == "Assign order").click().run()
    next(b for b in app.button if b.label == "Start work").click().run()
    app.radio(key="view").set_value("Technician feedback").run()
    # Pick the compatible actual cause and bundle; feedback reserves before consumption.
    next(s for s in app.selectbox if s.label == "Confirmed cause").select("OIL-COOLER")
    app.multiselect[0].select("PART-BIR-OIL-COOLER-01")
    next(b for b in app.button if b.label == "Record feedback").click().run()
    assert not app.exception
    assert any("Feedback recorded" in s.value for s in app.success)
    app.radio(key="view").set_value("Asset investigation").run()
    app.selectbox[1].select(12).run()
    next(b for b in app.button if b.label == "Advance replay").click().run()
    assert not app.exception
    svc = app.session_state["service"]
    assert svc.table("incidents").iloc[0].state == "resolved"
    assert svc.table("orders").iloc[0].state == "completed"
