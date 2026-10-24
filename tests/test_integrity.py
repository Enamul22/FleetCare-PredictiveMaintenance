import json
import os
import sqlite3
import subprocess
import pandas as pd
import pytest
from fleetcare.config import DATA, ROOT, FAULTS, SETTINGS
from fleetcare.service import Service
from fleetcare.simulation import generate
from fleetcare.pipeline import materialize
from fleetcare.temporal import supported_minutes
from fleetcare.evaluation import match_events
from fleetcare.reporting import filter_faults, page_slice


def test_time_support_endpoints_gaps_and_engine_off():
    f = pd.DataFrame(
        dict(timestamp=pd.date_range("2025-01-01", periods=49, freq="5min", tz="UTC"), engine_on=True)
    )
    assert supported_minutes(f).sum() == 240
    f.loc[10, "engine_on"] = False
    assert supported_minutes(f).sum() == 230
    f = f.drop(index=[20, 21, 22])
    assert supported_minutes(f).sum() == 210
    assert supported_minutes(f.iloc[:1]).sum() == 0


def test_bounded_matching_recurrences_duplicates_and_unmatched():
    events = [
        dict(
            event_id="one",
            case=0,
            code="FC-01",
            onset="2025-01-01T01:00Z",
            end="2025-01-01T01:30Z",
            failure_onset="2025-01-01T01:25Z",
        ),
        dict(
            event_id="two",
            case=0,
            code="FC-01",
            onset="2025-01-01T03:00Z",
            end="2025-01-01T03:30Z",
            failure_onset=None,
        ),
    ]
    times = ["00:55", "01:10", "01:15", "02:00", "03:10", "04:00"]
    predictions = [dict(case=0, code="FC-01", at=f"2025-01-01T{t}Z") for t in times]
    m = match_events(predictions, events)
    assert m["detected_events"] == 2 and m["duplicate_alerts"] == 1
    assert m["false_incidents"] == 3 and m["early_unmatched_alerts"] == 1 and m["late_unmatched_alerts"] == 2
    assert m["pre_failure_supported_events"] == m["pre_failure_warnings"] == 1
    assert m["median_detection_delay_minutes"] == 10
    simultaneous = events + [dict(events[0], event_id="three", code="FC-02")]
    m = match_events([dict(case=0, code="unexplained", at="2025-01-01T01:10Z")], simultaneous, generic=True)
    assert m["detected_events"] == 1


def test_cohort_reproducible_across_python_hash_seeds():
    code = """import hashlib,json,pandas as pd
from fleetcare.evaluation import cohort
frames,truth=cohort()
h=hashlib.sha256(json.dumps(truth,sort_keys=True).encode())
for f in frames: h.update(pd.util.hash_pandas_object(f,index=True).values.tobytes())
print(h.hexdigest())
"""
    results = []
    for seed in ["1", "723"]:
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT / "src"))
        results.append(
            subprocess.check_output([__import__("sys").executable, "-c", code], env=env, text=True).strip()
        )
    assert results[0] == results[1]


def test_full_pipeline_reproducible_and_all_rows_supported(tmp_path):
    source = tmp_path / "full"
    generate(source, full=True, n=12)
    outputs = [tmp_path / "first", tmp_path / "second"]
    tables = []
    for output in outputs:
        output.mkdir()
        (output / "baseline.json").write_bytes((DATA / "baseline.json").read_bytes())
        tables.append(materialize(source, output))
    pd.testing.assert_frame_equal(*tables)
    assert not (source / "replays.parquet").exists()
    for row in tables[0].itertuples():
        f = pd.read_parquet(outputs[0] / row.support_file)
        assert set(f.vehicle_id) == {row.vehicle_id}
        assert pd.Timestamp(row.started_at) in set(f.timestamp)


def test_filter_sort_pagination_download_and_one_row_per_fault(shared):
    s, a, path = shared
    all_rows = s.faults(a)
    filters = dict(
        country=all_rows.country.iloc[0], code=all_rows.code.iloc[0], search="veh-", sort="Oldest detection"
    )
    filtered = filter_faults(all_rows, filters)
    assert len(filtered) > 0
    assert filtered.confirmed_at.is_monotonic_increasing
    pages = [page_slice(all_rows, i, 7)[0] for i in range(1, (len(all_rows) + 6) // 7 + 1)]
    assert pd.concat(pages).fault_id.tolist() == all_rows.fault_id.tolist()
    assert len(pd.read_csv(__import__("io").StringIO(filtered.to_csv(index=False)))) == len(filtered)
    assert filter_faults(all_rows, {"search": "no-such-vehicle"}).empty
    assert all_rows.order_id.isna().all() and all_rows.rating.isna().all()


def test_legacy_migration_preserves_data_and_no_fake_responses(tmp_path):
    path = tmp_path / "legacy.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""create table incidents(id text primary key,vehicle_id text,code text,component_id text,severity text,state text,started text,last_seen text,recurrence_of text,evidence text,policy_version text,baseline_version text,playbook_version text,notification text);
    create table orders(id text primary key,incident_id text,state text,operational_status text,created_at text);
    create table feedback(id text primary key,order_id text,role text,finding text,cause text,action text,parts text,completed_at text,outcome text,notes text,effect real);
    create table audit(id integer primary key,at text,kind text,entity_id text,detail text);""")
    for i, state in enumerate(["assigned", "in_progress", "completed", "cancelled"]):
        fid = f"legacy-{i}"
        db.execute(
            "insert into incidents values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fid,
                "VEH-0001",
                "FC-01",
                "original",
                "warning",
                "active",
                "2025-12-15T09:00:00+00:00",
                "2025-12-15T10:00:00+00:00",
                None,
                "{}",
                "policy-1.0",
                "healthy-linear-1.0",
                "PB-1.0",
                "notify",
            ),
        )
        db.execute(
            "insert into orders values (?,?,?,?,?)",
            (f"old-{i}", fid, state, "ready", "2025-12-16T09:00:00+00:00"),
        )
    db.execute(
        "insert into feedback values (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "old-response",
            "old-2",
            "technician",
            "unknown",
            "unknown",
            "inspect_only",
            "{}",
            "2025-12-16T10:00:00+00:00",
            "not_resolved",
            "original notes",
            0.0,
        ),
    )
    db.execute(
        "insert into audit values (1,?,?,?,?)",
        ("2025-12-15T09:00Z", "original", "legacy", '{"original":true}'),
    )
    db.commit()
    original = {
        t: db.execute(f"select * from {t}").fetchall() for t in ["incidents", "orders", "feedback", "audit"]
    }
    db.close()
    s = Service(path)
    a = s.login("admin@fleetcare.example", "fleetcare-admin-demo")
    legacy = s.faults(a).query("run_id == 'legacy'")
    assert len(legacy) == 4 and legacy.order_status.tolist().count("Open") == 2
    assert set(legacy.order_status) == {"Open", "Completed", "Rejected"}
    assert legacy.response_decision.isna().all()
    assert len(s.legacy_feedback(a)) == 1
    for table in ["incidents", "orders", "feedback"]:
        assert [tuple(r) for r in s.db.execute(f"select * from {table}")] == original[table]
    assert (
        tuple(s.db.execute("select id,at,kind,entity_id,detail from audit where id=1").fetchone())
        == original["audit"][0]
    )
    count = len(s.faults(a))
    s.db.close()
    restart = Service(path)
    assert len(restart.faults(a)) == count


def test_ended_fault_can_receive_response_without_changing_end(shared):
    s, a, path = shared
    f = s.faults(a).iloc[0]
    # Evidence fixture from a previously observed sensor-recovery episode, not a customer decision.
    s.db.execute(
        "update faults set fault_status='Ended',ended_at='2025-12-20T10:00:00+00:00',recovery_confirmed_at='2025-12-20T10:20:00+00:00',sensor_verification='Recovery observed' where fault_id=?",
        (f.fault_id,),
    )
    oid = s.create_order(a, f.fault_id)["order_id"]
    c = s.login(f"customer{f.customer_id[-4:]}@fleetcare.example", "fleetcare-customer-demo")
    s.respond(c, oid, dict(decision="Completed", response_at="2026-10-24T12:00:00+00:00"))
    row = s.fault(a, f.fault_id)
    assert row["fault_status"] == "Ended" and row["ended_at"] == "2025-12-20T10:00:00+00:00"
    assert row["reported_resolution"] == "Not sure"


def test_private_credentials_replace_demo_access(tmp_path):
    from fleetcare.auth import hash_password

    config = [
        dict(
            user_id="private-admin",
            email="private-admin@example.test",
            display_name="Private review admin",
            role="admin",
            password_hash=hash_password("test-only-private-password"),
        )
    ]
    s = Service(tmp_path / "private.sqlite", auth_config=config)
    with pytest.raises(PermissionError):
        s.login("admin@fleetcare.example", "fleetcare-admin-demo")
    token = s.login("private-admin@example.test", "test-only-private-password")
    assert s.principal(token)["role"] == "admin"


def test_config_snapshots_match_runtime():
    config = json.loads((ROOT / "config/simulator.json").read_text())
    assert all(config[k] == v for k, v in SETTINGS.model_dump().items())
    policies = json.loads((ROOT / "config/policies.json").read_text())
    for code, p in FAULTS.items():
        assert policies["faults"][code]["warning"] == p[2]
        assert policies["faults"][code]["critical"] == p[3]
