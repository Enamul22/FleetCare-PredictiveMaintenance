# Manual launch, authentication and deployment

Owner: Enamul Haque / Enamul22 (GitHub ID 135505234). App name/version and app.py are unchanged.
No hosting deployment or account connection change was performed.

## Local shared demonstration

Python 3.12; install requirements.lock.txt, then `streamlit run app.py`. Default local saved store is the
repository's ignored fleetcare.sqlite. For hosted persistence use [Neon/PostgreSQL](NEON_SETUP.md). Override with `FLEETCARE_DB=/absolute/path/review.sqlite`.
Two browser tabs sign in independently and read/write that same saved store. Refresh saved changes
requeries it. Restart does not require reseeding/replaying workflow data. There is no customer reset button.

Public synthetic demo accounts:
- admin@fleetcare.example / fleetcare-admin-demo
- customerXXXX@fleetcare.example / fleetcare-customer-demo, where XXXX comes from CUS-XXXX.

The first displayed prepared fault belongs to CUS-0085. customer0000 is also a valid account and can
legitimately have no orders. All demo passwords are deliberately public; they are not a private-access
security boundary. No Enamul/password/email or real customer account is needed.

## Private review identity configuration

The supported local authentication is hashed-password sign-in, not a public role-switch control. Passwords
are PBKDF2-HMAC-SHA256 with random salts; opaque sessions are hashed, expire after eight hours and are revoked
on sign-out. Service queries validate roles and order ownership. Five failed sign-ins for an email within
five minutes trigger a temporary throttle. This is modest demo authentication, not production SSO/OIDC.

Generate each hash locally without placing a password on a command line:

```bash
PYTHONPATH=src python -m fleetcare.auth
```

Provide a private JSON file (outside Git; config/private-users.json is ignored) using this structure. Replace
the password_hash placeholders with generated hashes, and choose your own private review passwords.

```json
[
  {"user_id":"review-admin","email":"admin@example.test","display_name":"Review administrator","role":"admin","password_hash":"pbkdf2_sha256$..."},
  {"user_id":"review-customer-0085","email":"customer@example.test","display_name":"Assigned review customer","role":"customer","customer_id":"CUS-0085","password_hash":"pbkdf2_sha256$..."}
]
```

Launch with `FLEETCARE_AUTH_FILE=/private/path/users.json streamlit run app.py`. The file is validated;
at least one administrator is required, customer IDs must exist, and configured accounts replace enabled
demo access. Missing/invalid configuration fails instead of accepting an asserted role. No actual secrets
are committed. Use a separate review DB when switching between deliberately public and private account setups.

For Streamlit-hosted configuration, the same mapping can be supplied through secrets:

```toml
[fleetcare]
db_path = "fleetcare.sqlite"

[[fleetcare.users]]
user_id = "review-admin"
email = "admin@example.test"
display_name = "Review administrator"
role = "admin"
password_hash = "pbkdf2_sha256$..."

[[fleetcare.users]]
user_id = "review-customer-0085"
email = "customer@example.test"
display_name = "Assigned review customer"
role = "customer"
customer_id = "CUS-0085"
password_hash = "pbkdf2_sha256$..."
```

## Streamlit checklist after review

- Review current tests, matching/uncertainty limits, screenshots and successful CI for the exact commit.
- Sign in to Streamlit with Enamul's account; never use Priynka's deployment connection.
- Choose Enamul22/FleetCare-PredictiveMaintenance, main, entry point app.py, Python 3.12.
- Keep prepared data in the clone; never run full generation/training/detection at app startup.
- Configure review identities as above if restricting who can enter. Do not use real customer data.
- Verify admin row selection/Create → customer Open order → response → admin refresh in separate sessions.
- Verify another customer's signed-in session cannot read or change that order/evidence.
- Check Completed/Rejected history, rejected reason, null rating, response timestamps and independent fault status.
- Shared SQLite is for one running instance only. A hosted local file can disappear on sleep/restart/redeploy;
  multiple replicas would not share it. No reliable hosted durability or production multiuser readiness is claimed.
- Reliable durable hosting requires configuring the PostgreSQL adapter plus authentication/concurrency verification.
  The optional PostgreSQL adapter is now implemented; configure it using NEON_SETUP.md. SQLite remains
  available for local review.
- Any reset/reseed is an explicit offline developer action after backing up the DB; never delete historical
  records to work around migration failures. No real notifications, purchase orders or CRM writes are made.

## If hosted orders appear to disappear

Sign-out deletes only its login session and clears navigation. Select Order status → All in the same
customer account to distinguish hidden completed history from missing saved records. If history is
missing there too, investigate the hosted database: a container replacement/redeployment can remove
the local SQLite file, a changed db_path can open a different file, and db_path=":memory:" is deliberately
non-persistent. The normal default uses a shared file, not memory. Do not reset/reseed as a repair.

Streamlit [does not guarantee local file persistence](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).
Persistent hosted history needs the optional PostgreSQL adapter and a configured remote database; moving
the file to a different local folder is not enough. Follow NEON_SETUP.md to initialize and configure Neon. Avoid pushing/redeploying
a live review app merely to investigate missing history; export any still-readable records first.
