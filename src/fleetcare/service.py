"""Shared storage services: additive migration, explicit exports, tenant authorization and atomic responses."""

import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
import pandas as pd
from .config import DATA, FAULTS, TASKS, POLICY
from .auth import UserConfig, hash_password, verify_password
from .detection import Baseline
from .storage import SQLiteStore, PostgresStore, StorageError


class ConflictError(ValueError):
    """A different final response already exists; it must not be silently overwritten."""


SCHEMA = """
create table if not exists store_meta(key text primary key,value text);
create table if not exists customers(customer_id text primary key,customer_name text);
create table if not exists vehicles(vehicle_id text primary key,customer_id text references customers,
 model_id text,country text,city text);
create table if not exists users(user_id text primary key,email text unique,display_name text,
 role text check(role in ('admin','customer')),customer_id text references customers,password_hash text,enabled integer default 1);
create table if not exists sessions(token_hash text primary key,user_id text references users,expires_at text);
create table if not exists login_attempts(email text primary key,failures integer,last_at text);
create table if not exists faults(fault_id text primary key,vehicle_id text references vehicles,code text,fault_name text,
 component_id text,severity text,started_at text,confirmed_at text,ended_at text,recovery_confirmed_at text,
 last_detection_at text,last_observed_at text,fault_status text,sensor_verification text,
 policy_version text,baseline_version text,detection_version text,evidence text,support_file text,run_id text,legacy_state text);
create table if not exists export_requests(fault_id text primary key references faults,state text,
 attempts integer default 0,error text,snapshot text,customer_id text,requested_by text,requested_at text);
create table if not exists work_orders(order_id text primary key,fault_id text unique references faults,
 customer_id text references customers,status text check(status in ('Open','Completed','Rejected')),
 created_at text,created_by text,snapshot text,legacy_state text);
create table if not exists work_order_responses(response_id text primary key,order_id text unique references work_orders,
 user_id text,decision text check(decision in ('Completed','Rejected')),finding text,confirmed_cause text,
 action text,actual_parts text,reported_resolution text,rating integer check(rating between 1 and 5),notes text,
 rejection_reason text,response_at text,submitted_at text,payload text);
create table if not exists audit(id integer primary key,at text,kind text,entity_id text,detail text,actor text);
create view if not exists fault_reporting as
select f.*,v.customer_id,c.customer_name,v.model_id,v.country,v.city,
 coalesce(x.state,'Not created') creation_status,w.order_id,w.status order_status,w.created_at order_created_at,
 r.decision response_decision,r.finding,r.confirmed_cause,r.action,r.actual_parts,r.reported_resolution,
 r.rating,r.notes,r.rejection_reason,r.response_at,r.submitted_at
from faults f left join vehicles v on f.vehicle_id=v.vehicle_id
left join customers c on v.customer_id=c.customer_id
left join export_requests x on f.fault_id=x.fault_id
left join work_orders w on f.fault_id=w.fault_id
left join work_order_responses r on w.order_id=r.order_id;
"""


def now():
    return pd.Timestamp.now(tz="UTC").isoformat()


class Service:
    def __init__(self, path=None, data=DATA, auth_config=None, database_url=None, database_schema=None):
        self.data = Path(data)
        # Explicit SQLite paths isolate local tests/tools even if the host has a database URL.
        url = (
            database_url
            if database_url is not None
            else (os.environ.get("FLEETCARE_DATABASE_URL") if path is None else None)
        )
        database_schema = database_schema or os.environ.get("FLEETCARE_DATABASE_SCHEMA", "fleetcare")
        if url is not None:
            self.path = "PostgreSQL / " + database_schema
            self.db = PostgresStore(url, database_schema)
            if "store_meta" not in self.db.tables():
                self.db.close()
                raise StorageError(
                    "PostgreSQL is configured but not initialized. Run the offline FleetCare database migration using its direct connection first."
                )
            revision = self.db.execute("select value from store_meta where key='schema_pg'").fetchone()
            if not revision or revision[0] != "1":
                self.db.close()
                raise StorageError("The PostgreSQL schema needs the current FleetCare migration.")
        else:
            self.path = str(path or os.environ.get("FLEETCARE_DB", str(DATA.parents[1] / "fleetcare.sqlite")))
            self.db = SQLiteStore(self.path)
            self.db.executescript(SCHEMA)
            with self.atomic():
                if "actor" not in self.db.columns("audit"):
                    self.db.execute("alter table audit add column actor text")
        self.backend = self.db.backend
        self.seed_reference()
        self.migrate_legacy()
        config = auth_config
        if config is None and os.environ.get("FLEETCARE_AUTH_FILE"):
            config = json.loads(Path(os.environ["FLEETCARE_AUTH_FILE"]).read_text())
        self.configure_users(config)

    @contextmanager
    def atomic(self):
        with self.db.transaction():
            yield

    def log(self, kind, entity, detail, actor="system"):
        self.db.execute(
            "insert into audit(at,kind,entity_id,detail,actor) values (?,?,?,?,?)",
            (now(), kind, entity, json.dumps(detail, sort_keys=True, default=str), actor),
        )

    def seed_reference(self):
        manifest = self.data / "faults.parquet"
        if not manifest.exists():
            raise ValueError("Prepared complete-fleet faults are missing. Run the offline pipeline first.")
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        with self.atomic():
            current = self.db.execute("select value from store_meta where key='detection_sha256'").fetchone()
            if current and current[0] == digest:
                return
            a = pd.read_parquet(self.data / "assets.parquet")
            self.db.executemany(
                "insert into customers values (?,?) on conflict(customer_id) do update set customer_name=excluded.customer_name",
                list(
                    a[["customer_id", "customer_name"]].drop_duplicates().itertuples(index=False, name=None)
                ),
            )
            self.db.executemany(
                "insert into vehicles values (?,?,?,?,?) on conflict(vehicle_id) do update set customer_id=excluded.customer_id,model_id=excluded.model_id,country=excluded.country,city=excluded.city",
                list(
                    a[["vehicle_id", "customer_id", "model_id", "country", "city"]].itertuples(
                        index=False, name=None
                    )
                ),
            )
            f = pd.read_parquet(manifest)
            cols = [c for c in self.db.columns("faults") if c != "legacy_state"]
            values = [
                [None if pd.isna(row.get(k)) else row.get(k) for k in cols] for row in f.to_dict("records")
            ]
            # Refresh sensor evidence only; existing order and response snapshots stay immutable.
            updates = ",".join(f"{k}=excluded.{k}" for k in cols if k != "fault_id")
            self.db.executemany(
                f"insert into faults({','.join(cols)}) values ({','.join('?' for _ in cols)}) on conflict(fault_id) do update set {updates}",
                values,
            )
            self.db.execute(
                "insert into store_meta values ('detection_sha256',?) on conflict(key) do update set value=excluded.value",
                (digest,),
            )
            self.log("detection_dataset_imported", digest, dict(episodes=len(f)))

    def snapshot(self, fault):
        parts = pd.read_parquet(self.data / "parts.parquet")
        parts = parts[
            (parts.fault_code == fault["code"])
            & (parts.model_id == fault["model_id"])
            & (parts.component_type == fault["code"])
            & (parts.playbook_version == "PB-1.0")
        ]
        proposals = [
            dict(
                sku=p.sku,
                name=p.family.replace("-", " ").title(),
                family=p.family,
                quantity=int(p.quantity),
                conditional=True,
            )
            for p in parts.itertuples()
        ]
        investigation = TASKS[fault["code"]]
        return dict(
            playbook_id="PB-" + fault["code"][-2:],
            playbook_version="PB-1.0",
            policy_version=POLICY,
            baseline_version=fault["baseline_version"],
            baseline_parameters=Baseline(self.data / "baseline.json").parameters,
            policy=list(FAULTS[fault["code"]]),
            actions=[
                f"Review the supporting measurements for {fault['vehicle_id']} ({fault['model_id']}).",
                investigation,
                "Confirm the cause before selecting any replacement. Candidates are conditional, not a diagnosis.",
                "Report the performed action and outcome. Verify the condition from subsequent comparable sensor evidence.",
            ],
            parts=proposals,
            evidence_as_of=fault["last_observed_at"],
            fault_id=fault["fault_id"],
        )

    def migrate_legacy(self):
        with self.atomic():
            if self.db.execute("select 1 from store_meta where key='schema_r2'").fetchone():
                return
            tables = self.db.tables()
            if "incidents" in tables:
                for old in self.db.execute("select * from incidents").fetchall():
                    r = dict(old)
                    self.db.execute(
                        "insert into faults(fault_id,vehicle_id,code,fault_name,component_id,severity,started_at,confirmed_at,last_detection_at,last_observed_at,fault_status,sensor_verification,policy_version,baseline_version,detection_version,evidence,run_id,legacy_state) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict do nothing",
                        (
                            r["id"],
                            r["vehicle_id"],
                            r["code"],
                            FAULTS[r["code"]][-1],
                            r["component_id"],
                            r["severity"],
                            r["started"],
                            r["started"],
                            r["last_seen"],
                            r["last_seen"],
                            "Unknown",
                            "Legacy resolution recorded; exact end unavailable"
                            if r["state"] == "resolved"
                            else "Not observed",
                            r["policy_version"],
                            r["baseline_version"],
                            "legacy-import",
                            r["evidence"],
                            "legacy",
                            r["state"],
                        ),
                    )
                if "orders" in tables:
                    for old in self.db.execute("select * from orders").fetchall():
                        r = dict(old)
                        fault = self.db.execute(
                            "select * from fault_reporting where fault_id=?", (r["incident_id"],)
                        ).fetchone()
                        if not fault:
                            continue
                        status = {"completed": "Completed", "cancelled": "Rejected"}.get(r["state"], "Open")
                        snap = json.dumps(self.snapshot(fault), sort_keys=True)
                        self.db.execute(
                            "insert into work_orders values (?,?,?,?,?,?,?,?) on conflict do nothing",
                            (
                                r["id"],
                                r["incident_id"],
                                fault["customer_id"],
                                status,
                                r["created_at"],
                                "legacy-import",
                                snap,
                                r["state"],
                            ),
                        )
                        self.db.execute(
                            "insert into export_requests values (?,'Created',0,null,?,?,?,?) on conflict do nothing",
                            (r["incident_id"], snap, fault["customer_id"], "legacy-import", r["created_at"]),
                        )
                # Do not turn legacy report-only/customer notes into final customer decisions.
                # All original feedback, inventory, component and outbox rows remain in their original tables.
                self.log(
                    "legacy_migrated",
                    "schema-r2",
                    dict(
                        original_tables_preserved=sorted(tables),
                        state_mapping="created/assigned/in_progress -> Open; completed -> Completed; cancelled -> Rejected (legacy cancellation)",
                        responses="No final customer responses invented; legacy feedback remains separately readable",
                    ),
                )
            self.db.execute("insert into store_meta values ('schema_r2','2')")

    def configure_users(self, config):
        customers = self.db.execute("select * from customers order by customer_id").fetchall()
        if config is None:
            admin_hash = hash_password("fleetcare-admin-demo")
            customer_hash = hash_password("fleetcare-customer-demo")
            config = [
                dict(
                    user_id="admin",
                    email="admin@fleetcare.example",
                    display_name="Demo administrator",
                    role="admin",
                    password_hash=admin_hash,
                )
            ]
            config += [
                dict(
                    user_id=c["customer_id"],
                    email=f"customer{c['customer_id'][-4:]}@fleetcare.example",
                    display_name=c["customer_name"],
                    role="customer",
                    customer_id=c["customer_id"],
                    password_hash=customer_hash,
                )
                for c in customers
            ]
            self.auth_mode = "public_demo"
        else:
            self.auth_mode = "configured"
        users = [UserConfig.model_validate(v) for v in config]
        if not any(u.role == "admin" for u in users):
            raise ValueError("At least one configured administrator is required")
        with self.atomic():
            # Disabled accounts cannot retain session access after a private configuration is selected.
            if self.auth_mode == "configured":
                self.db.execute("update users set enabled=0")
            values = [
                (u.user_id, u.email.lower(), u.display_name, u.role, u.customer_id, u.password_hash)
                for u in users
            ]
            if self.auth_mode == "public_demo":
                self.db.executemany("insert into users values (?,?,?,?,?,?,1) on conflict do nothing", values)
            else:
                self.db.executemany(
                    "insert into users values (?,?,?,?,?,?,1) on conflict(user_id) do update set email=excluded.email,display_name=excluded.display_name,role=excluded.role,customer_id=excluded.customer_id,password_hash=excluded.password_hash,enabled=1",
                    values,
                )

    def login(self, email, password):
        email = email.strip().lower()
        with self.atomic():
            attempt = self.db.execute("select * from login_attempts where email=?", (email,)).fetchone()
            if (
                attempt
                and attempt["failures"] >= 5
                and (pd.Timestamp(now()) - pd.Timestamp(attempt["last_at"])).total_seconds() < 300
            ):
                raise PermissionError("Too many attempts. Try again after five minutes.")
            user = self.db.execute("select * from users where email=? and enabled=1", (email,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                failures = (
                    (attempt["failures"] + 1)
                    if attempt
                    and (pd.Timestamp(now()) - pd.Timestamp(attempt["last_at"])).total_seconds() < 300
                    else 1
                )
                self.db.execute(
                    "insert into login_attempts values (?,?,?) on conflict(email) do update set failures=excluded.failures,last_at=excluded.last_at",
                    (email, failures, now()),
                )
                token = None
            else:
                self.db.execute("delete from login_attempts where email=?", (email,))
                token = secrets.token_urlsafe(32)
                self.db.execute(
                    "insert into sessions values (?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        user["user_id"],
                        (pd.Timestamp(now()) + pd.Timedelta(hours=8)).isoformat(),
                    ),
                )
                self.log("signed_in", user["user_id"], {}, user["user_id"])
        if token is None:
            raise PermissionError("Sign-in failed. Check your email and password.")
        return token

    def principal(self, token):
        if not isinstance(token, str):
            raise PermissionError("Sign in to continue")
        row = self.db.execute(
            "select u.* from users u join sessions s on u.user_id=s.user_id where s.token_hash=? and s.expires_at>? and u.enabled=1",
            (hashlib.sha256(token.encode()).hexdigest(), now()),
        ).fetchone()
        if not row:
            raise PermissionError("Sign in to continue")
        return {k: row[k] for k in ["user_id", "email", "display_name", "role", "customer_id"]}

    def logout(self, token):
        with self.atomic():
            self.db.execute(
                "delete from sessions where token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )

    def admin(self, token):
        user = self.principal(token)
        if user["role"] != "admin":
            raise PermissionError("Administrator access required")
        return user

    def faults(self, token):
        self.admin(token)
        return self.db.frame("select * from fault_reporting order by confirmed_at desc,fault_id")

    def fault(self, token, fault_id):
        self.admin(token)
        row = self.db.execute("select * from fault_reporting where fault_id=?", (fault_id,)).fetchone()
        if not row:
            raise ValueError("Fault not found")
        return dict(row)

    def orders(self, token):
        user = self.principal(token)
        sql = "select f.* from fault_reporting f join work_orders w on f.order_id=w.order_id"
        if user["role"] == "customer":
            return self.db.frame(
                sql + " where w.customer_id=? order by w.created_at desc", [user["customer_id"]]
            )
        return self.db.frame(sql + " order by w.created_at desc")

    def order(self, token, order_id):
        user = self.principal(token)
        row = self.db.execute("select * from work_orders where order_id=?", (order_id,)).fetchone()
        if not row or user["role"] == "customer" and row["customer_id"] != user["customer_id"]:
            raise PermissionError("Order unavailable for this account")
        result = dict(row)
        result["snapshot"] = json.loads(result["snapshot"])
        result["fault"] = dict(
            self.db.execute("select * from fault_reporting where fault_id=?", (row["fault_id"],)).fetchone()
        )
        response = self.db.execute(
            "select * from work_order_responses where order_id=?", (order_id,)
        ).fetchone()
        result["response"] = dict(response) if response else None
        return result

    def create_order(self, token, fault_id, fail_export=False):
        user = self.admin(token)
        with self.atomic():
            existing = self.db.execute(
                "select order_id from work_orders where fault_id=?", (fault_id,)
            ).fetchone()
            if existing:
                return dict(ok=True, order_id=existing[0], status="Created")
            fault = self.fault(token, fault_id)
            request = self.db.execute(
                "select * from export_requests where fault_id=?", (fault_id,)
            ).fetchone()
            if not request:
                snap = json.dumps(self.snapshot(fault), sort_keys=True)
                self.db.execute(
                    "insert into export_requests values (?,'Pending',0,null,?,?,?,?)",
                    (fault_id, snap, fault["customer_id"], user["user_id"], now()),
                )
            self.db.execute(
                "update export_requests set attempts=attempts+1,state='Pending',error=null where fault_id=?",
                (fault_id,),
            )
            self.log("export_attempt", fault_id, {}, user["user_id"])
            if fail_export:
                self.db.execute(
                    "update export_requests set state='Failed',error='Mock service temporarily unavailable' where fault_id=?",
                    (fault_id,),
                )
                self.log("export_failed", fault_id, {}, user["user_id"])
                return dict(
                    ok=False,
                    order_id=None,
                    status="Failed",
                    error="Mock service temporarily unavailable. Retry this fault.",
                )
            request = self.db.execute(
                "select * from export_requests where fault_id=?", (fault_id,)
            ).fetchone()
            oid = "WO-" + hashlib.sha256(fault_id.encode()).hexdigest()[:16].upper()
            self.db.execute(
                "insert into work_orders values (?,?,?,'Open',?,?,?,null)",
                (oid, fault_id, request["customer_id"], now(), user["user_id"], request["snapshot"]),
            )
            self.db.execute(
                "update export_requests set state='Created',error=null where fault_id=?", (fault_id,)
            )
            self.log(
                "work_order_created",
                oid,
                dict(fault_id=fault_id, customer_id=request["customer_id"]),
                user["user_id"],
            )
            return dict(ok=True, order_id=oid, status="Created")

    def evidence(self, token, fault_id, order_id=None):
        user = self.principal(token)
        if user["role"] == "admin":
            fault = self.fault(token, fault_id)
        else:
            if not order_id:
                raise PermissionError("An assigned order is required")
            order = self.order(token, order_id)
            if order["fault_id"] != fault_id:
                raise PermissionError("Evidence does not belong to this order")
            fault = order["fault"]
        if fault["support_file"]:
            path = (self.data / fault["support_file"]).resolve()
            if not path.is_relative_to(self.data.resolve()):
                raise PermissionError("Invalid evidence path")
            frame = pd.read_parquet(path)
        else:
            tables = self.db.tables()
            if "observations" not in tables:
                return pd.DataFrame()
            records = self.db.execute(
                "select payload from observations where vehicle_id=? order by timestamp",
                (fault["vehicle_id"],),
            ).fetchall()
            frame = pd.DataFrame([json.loads(r[0]) for r in records])
            if frame.empty:
                return frame
            frame.timestamp = pd.to_datetime(frame.timestamp, utc=True)
        start = pd.Timestamp(fault["started_at"]) - pd.Timedelta(minutes=30)
        end = pd.Timestamp(fault["recovery_confirmed_at"] or fault["last_observed_at"]) + pd.Timedelta(
            minutes=30
        )
        return frame[(frame.timestamp >= start) & (frame.timestamp <= end)].copy().reset_index(drop=True)

    def respond(self, token, order_id, payload):
        user = self.principal(token)
        if user["role"] != "customer":
            raise PermissionError("Only the assigned signed-in customer can submit a response")
        order = self.order(token, order_id)
        data = self.validate_response(order, payload)
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
        with self.atomic():
            # Recheck ownership and terminal state inside the write transaction.
            order = self.order(token, order_id)
            prior = self.db.execute(
                "select * from work_order_responses where order_id=?", (order_id,)
            ).fetchone()
            if prior:
                if prior["payload"] == encoded:
                    return prior["response_id"]
                raise ConflictError(
                    "This order already has a different final response. Refresh to review it."
                )
            if order["status"] != "Open":
                raise ConflictError("This legacy/terminal order is read-only; no response may be invented.")
            rid = "RESP-" + hashlib.sha256(order_id.encode()).hexdigest()[:16]
            self.db.execute(
                "insert into work_order_responses values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    order_id,
                    user["user_id"],
                    data["decision"],
                    data["finding"],
                    data["confirmed_cause"],
                    data["action"],
                    json.dumps(data["actual_parts"], sort_keys=True)
                    if data["actual_parts"] is not None
                    else None,
                    data["reported_resolution"],
                    data["rating"],
                    data["notes"],
                    data["rejection_reason"],
                    data["response_at"],
                    now(),
                    encoded,
                ),
            )
            self.db.execute("update work_orders set status=? where order_id=?", (data["decision"], order_id))
            self.log("customer_response_saved", order_id, data, user["user_id"])
            return rid

    @staticmethod
    def validate_response(order, payload):
        decision = payload.get("decision")
        if decision not in ("Completed", "Rejected"):
            raise ValueError("Choose Completed or Rejected")
        rating = payload.get("rating")
        if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
            raise ValueError("Rating must be blank or an integer from 1 to 5")
        at = pd.Timestamp(payload.get("response_at"))
        if (
            pd.isna(at)
            or at.tzinfo is None
            or at > pd.Timestamp(now()) + pd.Timedelta(minutes=5)
            or at < pd.Timestamp(order["fault"]["confirmed_at"])
        ):
            raise ValueError(
                "Response time must include timezone, follow fault detection, and not be in the future"
            )
        data = dict(
            decision=decision,
            rating=rating,
            notes=str(payload.get("notes") or "").strip(),
            response_at=at.tz_convert("UTC").isoformat(),
            rejection_reason=None,
            finding=None,
            confirmed_cause=None,
            action=None,
            actual_parts=None,
            reported_resolution=None,
        )
        if decision == "Rejected":
            reason = str(payload.get("rejection_reason") or "").strip()
            if not reason:
                raise ValueError("A rejection reason is required")
            data["rejection_reason"] = reason
            return data
        finding = payload.get("finding", "unknown")
        if finding not in (
            "component_deterioration",
            "sensor_issue",
            "no_fault_found",
            "incorrect_recommendation",
            "unknown",
        ):
            raise ValueError("Invalid finding")
        cause = payload.get("confirmed_cause", "unknown")
        if cause not in ["unknown"] + [p["family"] for p in order["snapshot"]["parts"]]:
            raise ValueError("Cause does not apply to this fault")
        action = payload.get("action", "report_only")
        allowed = ["replacement", "inspection", "report_only"] + (
            ["connection_repair"] if order["fault"]["code"] == "FC-04" else []
        )
        if action not in allowed:
            raise ValueError("Action is not applicable")
        parts = payload.get("actual_parts", {})
        compatible = {p["sku"]: p["quantity"] for p in order["snapshot"]["parts"]}
        if not isinstance(parts, dict) or any(
            sku not in compatible or type(q) is not int or not 1 <= q <= compatible[sku]
            for sku, q in parts.items()
        ):
            raise ValueError("Actual parts/quantities must be compatible with this saved order")
        if action == "replacement" and not parts:
            raise ValueError("Replacement requires the actual compatible parts")
        if action != "replacement" and parts:
            raise ValueError("Actual replacement parts apply only to Replacement")
        resolution = payload.get("reported_resolution", "Not sure")
        if resolution not in ("Resolved", "Not resolved", "Not sure"):
            raise ValueError("Invalid reported resolution")
        data.update(
            finding=finding,
            confirmed_cause=cause,
            action=action,
            actual_parts=parts,
            reported_resolution=resolution,
        )
        return data

    def audit(self, token):
        self.admin(token)
        return self.db.frame("select * from audit order by id desc")

    def legacy_feedback(self, token):
        self.admin(token)
        if "feedback" not in self.db.tables():
            return pd.DataFrame()
        return self.db.frame("select * from feedback")
