import os
import subprocess
import sys
import uuid
import pytest
import psycopg
from psycopg import sql
from fleetcare.config import ROOT
from fleetcare.service import Service
from fleetcare.storage import PostgresStore, StorageError, validate_url
from fleetcare.database import migrate
from conftest import customer_for
from test_operations import payload


def test_backend_selection_and_remote_tls_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEETCARE_DATABASE_URL", "not-a-database-url")
    explicit_local = Service(tmp_path / "isolated.sqlite")
    assert explicit_local.backend == "sqlite"
    explicit_local.db.close()
    for url in [
        "",
        "not-a-database-url",
        "postgresql://u:secret@example.com/db?sslmode=disable",
        "sqlite://local",
    ]:
        with pytest.raises(StorageError) as exc:
            Service(database_url=url)
        assert "secret" not in str(exc.value)
    assert validate_url("postgresql://u:pw@localhost/db?sslmode=disable") == "disable"


def test_postgres_migration_rejects_pooler_before_connecting():
    with pytest.raises(StorageError, match="direct"):
        migrate("postgresql://u:p@ep-test-pooler.example/db?sslmode=require")


def test_remote_session_reconnect_and_process_restart(shared):
    s, a, path = shared
    if s.backend != "postgresql":
        pytest.skip("PostgreSQL-specific restart and migration check")
    f = s.faults(a).iloc[0].to_dict()
    oid = s.create_order(a, f["fault_id"])["order_id"]
    c = customer_for(s, f)
    rid = s.respond(c, oid, payload(rating=5, notes="durable restart evidence"))
    s.logout(c)
    s.db.close()
    # The adapter reconnects and reads committed records instead of reseeding workflow state.
    c = customer_for(s, f)
    assert s.order(c, oid)["response"]["response_id"] == rid
    migrate(os.environ["FLEETCARE_TEST_POSTGRES_URL"], s.db.schema)
    env = dict(os.environ, FLEETCARE_CHECK_ORDER=oid, PYTHONPATH=str(ROOT / "src"))
    code = """
import os
from fleetcare.service import Service
s=Service()
a=s.login('admin@fleetcare.example','fleetcare-admin-demo')
r=s.order(a,os.environ['FLEETCARE_CHECK_ORDER'])
assert r['status']=='Completed' and r['response']['notes']=='durable restart evidence'
assert len(s.faults(a))==70
print('fresh process retained response')
s.db.close()
"""
    result = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert "retained response" in result.stdout
    assert s.order(c, oid)["response"]["rating"] == 5


def test_uninitialized_postgres_does_not_fall_back_to_sqlite():
    url = os.environ.get("FLEETCARE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Real PostgreSQL URL required")
    with pytest.raises(StorageError, match="not initialized"):
        Service(database_url=url, database_schema="fleetcare_missing_" + uuid.uuid4().hex[:12])


def test_migration_preserves_unrelated_schema():
    url = os.environ.get("FLEETCARE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Real PostgreSQL URL required")
    schema = "fleetcare_test_" + uuid.uuid4().hex[:16]
    db = PostgresStore(url, schema)
    conn = db._connect()
    conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    try:
        conn.execute(sql.SQL("create table {}.unrelated (value text)").format(sql.Identifier(schema)))
        with pytest.raises(StorageError, match="unrelated"):
            migrate(url, schema)
        assert db.tables() == {"unrelated"}
        conn.execute(
            sql.SQL("create table {}.store_meta (key text primary key,value text)").format(
                sql.Identifier(schema)
            )
        )
        with pytest.raises(StorageError, match="Unknown"):
            migrate(url, schema)
        assert db.tables() == {"unrelated", "store_meta"}
    finally:
        conn.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
        db.close()


def test_postgres_retries_only_before_a_write_body(shared, monkeypatch):
    s, a, path = shared
    if s.backend != "postgresql":
        pytest.skip("PostgreSQL connection recovery semantics")
    original = s.db._context
    entries = []

    def stale_once(conn):
        entries.append(1)
        if len(entries) == 1:
            raise psycopg.OperationalError("simulate stale idle connection during setup")
        original(conn)

    monkeypatch.setattr(s.db, "_context", stale_once)
    bodies = []
    with s.atomic():
        bodies.append(1)
        s.db.execute("insert into store_meta values ('reconnect_test','saved')")
    assert len(entries) == 2 and len(bodies) == 1
    monkeypatch.setattr(s.db, "_context", original)
    failed_bodies = []
    with pytest.raises(StorageError):
        with s.atomic():
            failed_bodies.append(1)
            s.db.execute("insert into store_meta values ('must_rollback','no')")
            raise psycopg.OperationalError("simulate interrupted write")
    assert len(failed_bodies) == 1
    assert s.db.execute("select value from store_meta where key='must_rollback'").fetchone() is None
    assert s.db.execute("select value from store_meta where key='reconnect_test'").fetchone()[0] == "saved"
