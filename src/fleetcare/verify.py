"""Offline cross-session workflow acceptance; never affects a running visitor's database."""

import json
from pathlib import Path
import tempfile
from .config import ROOT
from .service import Service


def verify(output=ROOT / "evaluation/operational.json"):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "verify.sqlite"
        admin = Service(path)
        a = admin.login("admin@fleetcare.example", "fleetcare-admin-demo")
        initial = admin.faults(a)
        assert initial.order_id.isna().all()
        results = []
        for code in sorted(initial.code.unique()):
            f = initial[initial.code == code].iloc[0]
            created = admin.create_order(a, f.fault_id)
            oid = created["order_id"]
            assert admin.create_order(a, f.fault_id)["order_id"] == oid
            customer = Service(path)
            token = customer.login(
                f"customer{f.customer_id[-4:]}@fleetcare.example", "fleetcare-customer-demo"
            )
            request = dict(
                decision="Completed",
                finding="unknown",
                confirmed_cause="unknown",
                action="report_only",
                actual_parts={},
                reported_resolution="Not resolved",
                rating=None,
                notes="Synthetic acceptance; partial has no control effect",
                response_at="2026-10-24T12:00:00+00:00",
            )
            rid = customer.respond(token, oid, request)
            assert customer.respond(token, oid, request) == rid
            row = admin.fault(a, f.fault_id)
            assert row["order_status"] == "Completed" and row["reported_resolution"] == "Not resolved"
            assert row["fault_status"] == f.fault_status
            results.append(
                dict(
                    code=code,
                    fault_id=f.fault_id,
                    order_id=oid,
                    response_id=rid,
                    reported_resolution=row["reported_resolution"],
                    sensor_status_unchanged=True,
                )
            )
            customer.db.close()
        final = admin.faults(a)
        result = dict(
            public_app_version="1.0.0",
            workflow_revision="shared-response-r2",
            synthetic=True,
            detected_fault_rows=len(initial),
            joined_fault_rows=len(final),
            created_orders=int(final.order_id.notna().sum()),
            responses=int(final.response_decision.notna().sum()),
            duplicate_orders=int(final.order_id.dropna().duplicated().sum()),
            cases=results,
        )
        output.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return result


if __name__ == "__main__":
    verify()
