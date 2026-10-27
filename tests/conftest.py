import os
import uuid
import pytest
from psycopg import sql
from fleetcare.database import migrate
from fleetcare.storage import PostgresStore
from fleetcare.service import Service
from fleetcare.simulation import assets, scenario


@pytest.fixture
def curated():
    a = assets(12)

    def get(kind):
        index = {
            "FC-01": 0,
            "FC-02": 11,
            "FC-03": 2,
            "FC-04": 3,
            "FC-05": 4,
            "healthy_high_load": 5,
            "sensor_quality": 6,
            "missing_data": 7,
            "multi_fault": 8,
        }[kind]
        return scenario(a.iloc[index], kind)

    return get


@pytest.fixture(params=["sqlite", "postgresql"])
def shared(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        path = tmp_path / "operations.sqlite"
        s = Service(path)
        token = s.login("admin@fleetcare.example", "fleetcare-admin-demo")
        yield s, token, path
        s.db.close()
        return
    direct = os.environ.get("FLEETCARE_TEST_POSTGRES_URL")
    if not direct:
        pytest.skip("Set FLEETCARE_TEST_POSTGRES_URL to enable real PostgreSQL integration tests")
    pooled = os.environ.get("FLEETCARE_TEST_POSTGRES_POOLED_URL", direct)
    schema = "fleetcare_test_" + uuid.uuid4().hex[:16]
    migrate(direct, schema)
    monkeypatch.setenv("FLEETCARE_DATABASE_URL", pooled)
    monkeypatch.setenv("FLEETCARE_DATABASE_SCHEMA", schema)
    try:
        s = Service()
        token = s.login("admin@fleetcare.example", "fleetcare-admin-demo")
        yield s, token, None
    finally:
        if "s" in locals():
            s.db.close()
        # Only this fixture's newly-created isolated synthetic schema is disposable.
        cleanup = PostgresStore(direct, schema)
        try:
            cleanup._connect().execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
        finally:
            cleanup.close()


def customer_for(service, fault):
    return service.login(f"customer{fault['customer_id'][-4:]}@fleetcare.example", "fleetcare-customer-demo")
