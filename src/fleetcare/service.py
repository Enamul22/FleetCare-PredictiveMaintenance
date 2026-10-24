"""SQLite operations, transactional outbox, lifecycle and interactive simulation branches."""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from contextlib import contextmanager
import uuid
import pandas as pd
from .config import FAULTS, POLICY, BASELINE, FAMILIES, SETTINGS
from .detection import classify, Baseline
from .ingestion import Sources, candidates
from .simulation import observe

DDL = """
create table if not exists incidents(id text primary key, vehicle_id text, code text, component_id text,
 severity text, state text, started text, last_seen text, recurrence_of text, evidence text,
 policy_version text, baseline_version text, playbook_version text, notification text);
create unique index if not exists one_active on incidents(vehicle_id,code,component_id) where state!='resolved';
create table if not exists outbox(id text primary key, incident_id text unique, attempts integer default 0,
 state text default 'pending', error text);
create table if not exists orders(id text primary key, incident_id text unique, state text,
 operational_status text, created_at text);
create table if not exists inventory(sku text primary key, available integer, reserved integer default 0, consumed integer default 0);
create table if not exists lines(order_id text, sku text, recommended integer default 1, reserved integer default 0,
 consumed integer default 0, returned integer default 0, unavailable integer default 0, primary key(order_id,sku));
create table if not exists feedback(id text primary key,order_id text,role text,finding text,cause text,
 action text,parts text,completed_at text,outcome text,notes text,effect real);
create table if not exists components(id text primary key,vehicle_id text,code text,installed_at text,replaced_at text);
create table if not exists observations(vehicle_id text,timestamp text,payload text,primary key(vehicle_id,timestamp));
create table if not exists deliveries(id text primary key,sku text,quantity integer);
create table if not exists processed(vehicle_id text,timestamp text,primary key(vehicle_id,timestamp));
create table if not exists replay(scenario text primary key,cursor integer,branch text);
create table if not exists audit(id integer primary key,at text,kind text,entity_id text,detail text);
create table if not exists quality(vehicle_id text primary key,status text,at text);
"""


class Service:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys=ON")
        self.db.executescript(DDL)
        self.baseline = Baseline()
        with self.atomic():
            for p in Sources().erp().itertuples():
                self.db.execute(
                    "insert or ignore into inventory(sku,available) values (?,?)", (p.sku, p.stock)
                )

    @contextmanager
    def atomic(self):
        name = "sp_" + uuid.uuid4().hex
        self.db.execute(f"savepoint {name}")
        try:
            yield
            self.db.execute(f"release savepoint {name}")
        except Exception:
            self.db.execute(f"rollback to savepoint {name}")
            self.db.execute(f"release savepoint {name}")
            raise

    def table(self, name):
        if name not in {
            "incidents",
            "outbox",
            "orders",
            "inventory",
            "lines",
            "feedback",
            "components",
            "audit",
            "quality",
            "replay",
            "deliveries",
        }:
            raise ValueError("Invalid table")
        return pd.read_sql_query(f"select * from {name}", self.db)

    def log(self, kind, entity, detail, at=None):
        self.db.execute(
            "insert into audit(at,kind,entity_id,detail) values (?,?,?,?)",
            (at or datetime.now(timezone.utc).isoformat(), kind, entity, json.dumps(detail, default=str)),
        )

    def component(self, vehicle, code):
        row = self.db.execute(
            "select id from components where vehicle_id=? and code=? and replaced_at is null", (vehicle, code)
        ).fetchone()
        if row:
            return row[0]
        cid = f"{vehicle}:{code}:original"
        self.db.execute(
            "insert into components values (?,?,?,?,null)", (cid, vehicle, code, "2025-01-01T00:00:00Z")
        )
        return cid

    def ingest(self, frame):
        """All incident/outbox changes commit with the ingestion checkpoint."""
        if frame.empty:
            return
        f = frame.sort_values("timestamp").drop_duplicates(["vehicle_id", "timestamp"])
        if f.vehicle_id.nunique() != 1:
            raise ValueError("Ingest one canonical vehicle at a time")
        duplicates = 0
        with self.atomic():
            for pos in range(len(f)):
                row = f.iloc[pos]
                v = row.vehicle_id
                at = row.timestamp.isoformat()
                if self.db.execute(
                    "select 1 from processed where vehicle_id=? and timestamp=?", (v, at)
                ).fetchone():
                    duplicates += 1
                    continue
                latest = self.db.execute(
                    "select max(timestamp) from processed where vehicle_id=?", (v,)
                ).fetchone()[0]
                if latest is not None and at < latest:
                    raise ValueError("Out-of-order new observations require an explicit offline replay")
                payload = row.to_dict()
                payload["timestamp"] = at
                self.db.execute(
                    "insert or ignore into observations values (?,?,?)",
                    (v, at, json.dumps(payload, default=str)),
                )
                history = self.db.execute(
                    "select payload from observations where vehicle_id=? and timestamp<=? order by timestamp",
                    (v, at),
                ).fetchall()
                past = pd.DataFrame([json.loads(h[0]) for h in history])
                past["timestamp"] = pd.to_datetime(past.timestamp, utc=True)
                quality = "observed" if row.quality_status == "valid" else "unknown / " + row.quality_status
                prior_quality = self.db.execute(
                    "select status from quality where vehicle_id=?", (v,)
                ).fetchone()
                if quality != "observed" and (not prior_quality or prior_quality[0] != quality):
                    self.log("telemetry_quality_incident", v, dict(status=quality, condition="unknown"), at)
                self.db.execute("insert or replace into quality values (?,?,?)", (v, quality, at))
                for code in FAULTS:
                    status, e = classify(past, code, self.baseline)
                    current = self.db.execute(
                        "select * from incidents where vehicle_id=? and code=? and state!='resolved'",
                        (v, code),
                    ).fetchone()
                    if status in ("warning", "critical"):
                        last = e.iloc[-1]
                        policy = FAULTS[code]
                        duration = 5 if status == "critical" else policy[4]
                        window = e[e.timestamp >= row.timestamp - pd.Timedelta(minutes=duration)]
                        proof = json.dumps(
                            dict(
                                sensor=policy[0],
                                comparison=policy[1],
                                trigger_severity=status,
                                threshold=policy[3] if status == "critical" else policy[2],
                                window_minutes=duration,
                                cadence_minutes=SETTINGS.cadence_minutes,
                                valid_samples=int(window.valid.sum()),
                                expected_samples=duration // SETTINGS.cadence_minutes + 1,
                                observed=float(last.observed),
                                expected=float(last.expected),
                                value=float(last.value),
                                timestamp=at,
                            )
                        )
                        if current:
                            severity = (
                                "critical"
                                if status == "critical" or current["severity"] == "critical"
                                else "warning"
                            )
                            self.db.execute(
                                "update incidents set severity=?,state='active',last_seen=?,evidence=?,notification=? where id=?",
                                (
                                    severity,
                                    at,
                                    proof,
                                    "notify" if severity == "critical" else current["notification"],
                                    current["id"],
                                ),
                            )
                            if severity != current["severity"]:
                                self.log("severity_escalated", current["id"], severity, at)
                        else:
                            cid = self.component(v, code)
                            previous = self.db.execute(
                                "select id,last_seen from incidents where vehicle_id=? and code=? order by started desc limit 1",
                                (v, code),
                            ).fetchone()
                            iid = hashlib.sha256(f"{v}|{code}|{cid}|{at}".encode()).hexdigest()[:18]
                            cool = (
                                previous
                                and (row.timestamp - pd.Timestamp(previous["last_seen"])).total_seconds()
                                < SETTINGS.cooldown_minutes * 60
                            )
                            notification = (
                                "cooldown_suppressed" if cool and status != "critical" else "notify"
                            )
                            self.db.execute(
                                "insert into incidents values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (
                                    iid,
                                    v,
                                    code,
                                    cid,
                                    status,
                                    "active",
                                    at,
                                    at,
                                    previous["id"] if previous else None,
                                    proof,
                                    POLICY,
                                    BASELINE,
                                    "PB-1.0",
                                    notification,
                                ),
                            )
                            self.db.execute(
                                "insert into outbox(id,incident_id) values (?,?)", (f"export:{iid}", iid)
                            )
                            self.log(
                                "incident_created",
                                iid,
                                dict(code=code, status=status, notification=notification),
                                at,
                            )
                    elif current and status == "recovered":
                        self.db.execute(
                            "update incidents set state='resolved',last_seen=? where id=?",
                            (at, current["id"]),
                        )
                        self.db.execute(
                            "update orders set operational_status='sensor_verified' where incident_id=? and state='completed'",
                            (current["id"],),
                        )
                        self.log("sensor_verified_resolution", current["id"], dict(window_minutes=15), at)
                    elif current and bool(e.valid.iloc[-1]):
                        _, kind, _, _, _, threshold, _ = FAULTS[code]
                        val = e.value.iloc[-1]
                        improving = val > threshold if kind == "ratio_low" else val < threshold
                        if improving and current["state"] != "recovering":
                            self.db.execute(
                                "update incidents set state='recovering' where id=?", (current["id"],)
                            )
                            self.log("recovery_started", current["id"], {}, at)
                self.db.execute("insert into processed values (?,?)", (v, at))
            if duplicates:
                self.log("duplicate_input_suppressed", f.vehicle_id.iloc[0], dict(observations=duplicates))

    def export(self, fail=False):
        """Mock receiver shares transaction; incident identity is its permanent idempotency key."""
        for row in self.db.execute("select * from outbox where state!='acknowledged'").fetchall():
            with self.atomic():
                self.db.execute("update outbox set attempts=attempts+1 where id=?", (row["id"],))
                self.log("export_attempt", row["incident_id"], dict(failed=fail))
                if fail:
                    self.db.execute(
                        "update outbox set error='Simulated transport interruption',state='retry' where id=?",
                        (row["id"],),
                    )
                    continue
                oid = f"WO-{row['incident_id']}"
                self.db.execute(
                    "insert or ignore into orders values (?,?,'created','ready',?)",
                    (oid, row["incident_id"], datetime.now(timezone.utc).isoformat()),
                )
                ctx = self.order_context(oid)
                model = Sources().crm().set_index("vehicle_id").loc[ctx["vehicle_id"], "model_id"]
                for sku in candidates(ctx["code"], model, ctx["code"]).sku:
                    self.db.execute(
                        "insert or ignore into lines(order_id,sku,recommended) values (?,?,1)", (oid, sku)
                    )
                self.db.execute("update outbox set state='acknowledged',error=null where id=?", (row["id"],))
                self.log("export_acknowledged", oid, dict(idempotency_key=row["id"]))

    def transition(self, order_id, state):
        allowed = {
            "created": {"assigned", "cancelled"},
            "assigned": {"in_progress", "cancelled"},
            "in_progress": {"cancelled"},
        }
        with self.atomic():
            row = self.db.execute("select state from orders where id=?", (order_id,)).fetchone()
            if not row or state not in allowed.get(row[0], set()):
                raise ValueError("Invalid work-order transition; completion requires structured feedback")
            if state == "cancelled":
                for line in self.db.execute("select * from lines where order_id=?", (order_id,)).fetchall():
                    self.db.execute(
                        "update inventory set available=available+?,reserved=reserved-? where sku=?",
                        (line["reserved"], line["reserved"], line["sku"]),
                    )
                    self.db.execute(
                        "update lines set returned=returned+reserved,reserved=0 where order_id=? and sku=?",
                        (order_id, line["sku"]),
                    )
            self.db.execute("update orders set state=? where id=?", (state, order_id))
            self.log("work_order_transition", order_id, state)

    def order_context(self, order_id):
        return self.db.execute(
            "select i.*,o.state order_state from incidents i join orders o on i.id=o.incident_id where o.id=?",
            (order_id,),
        ).fetchone()

    def reserve(self, order_id, sku):
        with self.atomic():
            ctx = self.order_context(order_id)
            if not ctx or ctx["order_state"] in ("completed", "cancelled"):
                raise ValueError("Order is not open")
            model = Sources().crm().set_index("vehicle_id").loc[ctx["vehicle_id"], "model_id"]
            if sku not in set(candidates(ctx["code"], model, ctx["code"]).sku):
                raise ValueError("Incompatible part")
            old = self.db.execute(
                "select reserved,consumed from lines where order_id=? and sku=?", (order_id, sku)
            ).fetchone()
            if old and (old[0] or old[1]):
                return True
            stock = self.db.execute("select available from inventory where sku=?", (sku,)).fetchone()[0]
            self.db.execute("insert or ignore into lines(order_id,sku) values (?,?)", (order_id, sku))
            if stock < 1:
                self.db.execute("update lines set unavailable=1 where order_id=? and sku=?", (order_id, sku))
                self.db.execute(
                    "update orders set operational_status='waiting_for_parts' where id=?", (order_id,)
                )
                self.log("stockout", order_id, sku)
                return False
            self.db.execute(
                "update inventory set available=available-1,reserved=reserved+1 where sku=?", (sku,)
            )
            self.db.execute(
                "update lines set reserved=1,unavailable=0 where order_id=? and sku=?", (order_id, sku)
            )
            remaining = self.db.execute(
                "select count(*) from lines where order_id=? and unavailable>0", (order_id,)
            ).fetchone()[0]
            if remaining == 0:
                self.db.execute("update orders set operational_status='ready' where id=?", (order_id,))
            self.log("part_reserved", order_id, sku)
            return True

    def receive_delivery(self, delivery_id, sku, quantity=1):
        if not isinstance(quantity, int) or quantity < 1:
            raise ValueError("Delivery quantity must be positive integer")
        with self.atomic():
            existing = self.db.execute(
                "select sku,quantity from deliveries where id=?", (delivery_id,)
            ).fetchone()
            if existing:
                if tuple(existing) != (sku, quantity):
                    raise ValueError("Conflicting delivery idempotency key")
                return
            if not self.db.execute("select 1 from inventory where sku=?", (sku,)).fetchone():
                raise ValueError("Unknown ERP SKU")
            self.db.execute("insert into deliveries values (?,?,?)", (delivery_id, sku, quantity))
            self.db.execute("update inventory set available=available+? where sku=?", (quantity, sku))
            self.log("mock_erp_receipt", delivery_id, dict(sku=sku, quantity=quantity))

    def feedback(
        self, feedback_id, order_id, role, finding, cause, action, parts, outcome, notes="", at=None
    ):
        if role not in ("technician", "customer") or outcome not in ("resolved", "not_resolved", "unknown"):
            raise ValueError("Invalid feedback role/outcome")
        with self.atomic():
            existing = self.db.execute("select * from feedback where id=?", (feedback_id,)).fetchone()
            if existing:
                if (
                    existing["order_id"] != order_id
                    or existing["action"] != action
                    or existing["cause"] != cause
                    or json.loads(existing["parts"]) != parts
                ):
                    raise ValueError("Idempotency key belongs to another order")
                return existing["effect"]
            ctx = self.order_context(order_id)
            if not ctx:
                raise ValueError("Unknown work order")
            if role == "technician" and ctx["order_state"] != "in_progress":
                raise ValueError("Technician completion requires in_progress order")
            if role == "customer" and (parts or action != "report_only"):
                raise ValueError("Customer reports cannot perform workshop actions")
            if action not in ("replace", "inspect_only", "connection_repair", "report_only"):
                raise ValueError("Unknown action")
            if action == "replace" and not parts:
                raise ValueError("Replacement requires a compatible part")
            if parts and action != "replace":
                raise ValueError("Actual replacement parts require replacement action")
            if any(q != 1 for q in parts.values()):
                raise ValueError("Demo bundles use quantity one")
            model = Sources().crm().set_index("vehicle_id").loc[ctx["vehicle_id"], "model_id"]
            valid = set(candidates(ctx["code"], model, ctx["code"]).sku)
            for sku in parts:
                if cause == "unknown" or f"-{cause}-01" not in sku:
                    raise ValueError("Actual parts must support the confirmed finding")
                line = self.db.execute(
                    "select reserved from lines where order_id=? and sku=?", (order_id, sku)
                ).fetchone()
                if sku not in valid or not line or line[0] < 1:
                    raise ValueError("Parts must be compatible, available and reserved before consumption")
            # Scenario engine's recorded efficacy; inference never reads this state.
            correct = cause == FAMILIES[ctx["code"]][0] and (
                any(f"-{cause}-01" in sku for sku in parts)
                or action == "connection_repair"
                and cause == "CONNECTION-KIT"
            )
            effect = 1.0 if correct and action in ("replace", "connection_repair") else 0.0
            if "partial" in notes.lower() and correct:
                effect = 0.45
            if at is None:
                for state in self.db.execute("select * from replay").fetchall():
                    original = Sources().telemetry(state["scenario"])
                    if len(original) and original.vehicle_id.iloc[0] == ctx["vehicle_id"]:
                        at = (
                            original.timestamp.iloc[0] + pd.Timedelta(minutes=state["cursor"] * 5)
                        ).isoformat()
                        break
            at = at or datetime.now(timezone.utc).isoformat()
            event_time = pd.Timestamp(at)
            if event_time.tzinfo is None or event_time < pd.Timestamp(ctx["started"]):
                raise ValueError("Completion timestamp must be timezone-aware and after incident onset")
            at = event_time.tz_convert("UTC").isoformat()
            self.db.execute(
                "insert into feedback values (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    feedback_id,
                    order_id,
                    role,
                    finding,
                    cause,
                    action,
                    json.dumps(parts),
                    at,
                    outcome,
                    notes,
                    effect,
                ),
            )
            if role == "customer":
                self.log("customer_report", feedback_id, dict(outcome=outcome), at)
                return effect
            for line in self.db.execute("select * from lines where order_id=?", (order_id,)).fetchall():
                used = parts.get(line["sku"], 0)
                returned = line["reserved"] - used
                self.db.execute(
                    "update inventory set reserved=reserved-?,consumed=consumed+?,available=available+? where sku=?",
                    (line["reserved"], used, returned, line["sku"]),
                )
                self.db.execute(
                    "update lines set consumed=consumed+?,returned=returned+?,reserved=0 where order_id=? and sku=?",
                    (used, returned, order_id, line["sku"]),
                )
            self.db.execute(
                "update orders set state='completed',operational_status='verification_pending' where id=?",
                (order_id,),
            )
            if action == "replace":
                old = self.component(ctx["vehicle_id"], ctx["code"])
                self.db.execute("update components set replaced_at=? where id=?", (at, old))
                self.db.execute(
                    "insert into components values (?,?,?,?,null)",
                    (f"{old}:{feedback_id}", ctx["vehicle_id"], ctx["code"], at),
                )
            self.log(
                "feedback_completed",
                feedback_id,
                dict(effect=effect, outcome=outcome, sensor_verification="pending"),
                at,
            )
            # Persist branch at actual replay cursor, so later observations depend on the selected action.
            for state in self.db.execute("select * from replay").fetchall():
                original = Sources().telemetry(state["scenario"])
                if not original.empty and original.vehicle_id.iloc[0] == ctx["vehicle_id"]:
                    branch = json.loads(state["branch"])
                    branch[ctx["code"]] = dict(effect=effect, at=state["cursor"], feedback_id=feedback_id)
                    self.db.execute(
                        "update replay set branch=? where scenario=?", (json.dumps(branch), state["scenario"])
                    )
            return effect

    def replay_frame(self, scenario):
        f = Sources().telemetry(scenario)
        row = self.db.execute("select * from replay where scenario=?", (scenario,)).fetchone()
        if row:
            branch = json.loads(row["branch"])
            # A late repair receives an additional two-hour verification horizon.
            if branch:
                horizon = max(max(int(b["at"]) for b in branch.values()) + 25, len(f))
                if horizon > len(f):
                    vehicle = Sources().crm().set_index("vehicle_id").loc[f.vehicle_id.iloc[0]].to_dict()
                    vehicle["vehicle_id"] = f.vehicle_id.iloc[0]
                    timestamps = pd.date_range(f.timestamp.iloc[0], periods=horizon, freq="5min")
                    codes = ["FC-01", "FC-04"] if scenario == "multi_fault" else [scenario]
                    extra = observe(vehicle, timestamps, 44, {c: 0.82 for c in codes})
                    extra["scenario"] = scenario
                    extra = extra.iloc[len(f) :].copy()
                    previous = f.iloc[-1]
                    extra["odometer_km"] = (
                        float(previous.odometer_km) + (extra.vehicle_speed_kmh / 12).cumsum()
                    )
                    extra["lifetime_engine_hours"] = float(previous.lifetime_engine_hours) + (
                        pd.Series(range(1, len(extra) + 1), index=extra.index) / 12
                    )
                    f = pd.concat([f, extra], ignore_index=True)
            for code, b in branch.items():
                index = int(b["at"])
                if index >= len(f):
                    continue
                vehicle = Sources().crm().set_index("vehicle_id").loc[f.vehicle_id.iloc[0]].to_dict()
                vehicle["vehicle_id"] = f.vehicle_id.iloc[0]
                conditions = {}
                codes = ["FC-01", "FC-04"] if scenario == "multi_fault" else [scenario]
                for c in codes:
                    conditions[c] = 0.82 * (1 - b["effect"]) if c == code else 0.82
                future = observe(vehicle, f.timestamp, 44, conditions)
                # Preserve operating state/clock and other sensors, change only affected sensor.
                sensor = FAULTS[code][0]
                f.loc[index:, sensor] = future.loc[index:, sensor]
                component = self.db.execute(
                    "select id from components where vehicle_id=? and code=? and replaced_at is null",
                    (vehicle["vehicle_id"], code),
                ).fetchone()
                if component:
                    for j in range(index, len(f)):
                        ids = json.loads(f.loc[j, "installed_component_ids"])
                        ids[code] = component[0]
                        f.loc[j, "installed_component_ids"] = json.dumps(ids)
        return f

    def advance(self, scenario, steps=3, fail_export=False):
        row = self.db.execute("select * from replay where scenario=?", (scenario,)).fetchone()
        cursor = row["cursor"] if row else 0
        f = self.replay_frame(scenario)
        if not isinstance(steps, int) or steps < 1:
            raise ValueError("Replay steps must be a positive integer")
        end = min(len(f), cursor + steps)
        # A failure rolls back cursor and incident updates together.
        with self.atomic():
            self.ingest(f.iloc[:end])
            self.db.execute(
                "insert into replay values (?,?,?) on conflict(scenario) do update set cursor=excluded.cursor",
                (scenario, end, row["branch"] if row else "{}"),
            )
        self.export(fail_export)
        return end
