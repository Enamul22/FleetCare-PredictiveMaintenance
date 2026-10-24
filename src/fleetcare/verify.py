"""Reproducible operational acceptance evidence. No remote systems are contacted."""

import json
from .config import ROOT, FAMILIES
from .service import Service
from .ingestion import Sources


def verify(output=ROOT / "evaluation/operational.json"):
    s = Service()
    cases = []
    for code, families in FAMILIES.items():
        s.advance(code, 15, fail_export=True)
        s.export()
        s.export()
        inc = s.table("incidents").query("code == @code").iloc[0]
        oid = s.table("orders").query("incident_id == @inc.id").iloc[0].id
        s.transition(oid, "assigned")
        s.transition(oid, "in_progress")
        model = Sources().crm().set_index("vehicle_id").loc[inc.vehicle_id, "model_id"]
        sku = f"PART-{model}-{families[0]}-01"
        if not s.reserve(oid, sku):
            s.receive_delivery(f"delivery:{code}", sku)
            s.reserve(oid, sku)
        fid = f"feedback:{code}"
        args = (
            fid,
            oid,
            "technician",
            "component_deterioration",
            families[0],
            "replace",
            {sku: 1},
            "resolved",
        )
        s.feedback(*args)
        s.feedback(*args)
        s.advance(code, 15)
        s.ingest(s.replay_frame(code).iloc[:30])
        ctx = s.order_context(oid)
        assert ctx["state"] == "resolved"
        cases.append(
            dict(code=code, order_id=oid, incident_id=inc.id, verified=ctx["state"], consumed_sku=sku)
        )
    orders = s.table("orders")
    result = dict(
        version="operational-1.0",
        cases=cases,
        orders=len(orders),
        duplicates=int(orders.incident_id.duplicated().sum()),
        consumed_units=int(s.table("inventory").consumed.sum()),
        feedback=len(s.table("feedback")),
        retries=int(s.table("outbox").attempts.sum()),
        duplicate_rate=float(orders.incident_id.duplicated().mean()),
        synthetic=True,
    )
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    verify()
