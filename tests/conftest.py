import pytest
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


@pytest.fixture
def shared(tmp_path):
    path = tmp_path / "operations.sqlite"
    s = Service(path)
    token = s.login("admin@fleetcare.example", "fleetcare-admin-demo")
    return s, token, path


def customer_for(service, fault):
    return service.login(f"customer{fault['customer_id'][-4:]}@fleetcare.example", "fleetcare-customer-demo")
