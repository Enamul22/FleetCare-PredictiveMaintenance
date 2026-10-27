# Persistent hosted history with Neon/PostgreSQL

FleetCare remains version 1.0.0. This optional backend stores small operational records in Lakebase
Postgres on Neon; Streamlit continues to host the Python application. Telemetry/Parquet files stay in Git.
There is no Neon Auth, Data API, object-storage or frontend rewrite.

## Current owner review setup

On 27 October 2026 the permanent production branch was initialized with schema `fleetcare`, all 70
prepared faults and zero work orders/responses. Temporary browser/test orders were not copied into it.
The owner’s ignored `.env.neon-streamlit.toml` file contains the production pooled settings, mode 0600;
it is a private local handoff file, not an automatically loaded app configuration. Merge its keys into
hosting Secrets only after reviewing the code. The live Streamlit configuration was not changed.

## Connection and schema setup

1. Use Enamul's verified FleetCare Neon project, Free plan, Frankfurt. Keep its default production branch
   for persistent history. The `fleetcare-persistence-review-20261027` child branch is temporary and expires;
   **never configure the deployed application with a temporary test branch's URL**.
2. In Neon Connect select the production branch/database/role. Copy its **direct** connection privately.
   From the reviewed repository and locked environment, initialize the `fleetcare` schema:

   ```bash
   PYTHONPATH=src .venv/bin/python -m fleetcare.database --prompt --seed
   ```

   Paste the direct URL into the hidden prompt. Alternatively set `FLEETCARE_DATABASE_URL_DIRECT` privately
   and omit `--prompt`. Do not put connection URLs in shell command history, chat, screenshots or Git.
   The versioned migration is `migrations/001_postgres.sql`. It uses a direct connection and refuses a
   `-pooler` migration URL or a schema containing unrelated tables. A migration rerun does not reset orders.
   `--seed` imports all prepared vehicles/customers/faults; it creates no work orders/responses.
3. Copy the production **pooled** TLS connection for application traffic. Put it in Streamlit Secrets:

   ```toml
   [fleetcare]
   database_url = "postgresql://ROLE:ENCODED_PASSWORD@PRODUCTION_POOLER_HOST/neondb?sslmode=require&channel_binding=require"
   database_schema = "fleetcare"
   ```

   Merge these two keys into an existing `[fleetcare]` section; do not duplicate the section or discard
   configured `users`. Do not copy the hidden direct migration URL to the app unless another tool needs it.
   Actual credentials remain private. An optional local private file is ignored at `.streamlit/secrets.toml`.
   The committed config/neon-secrets.example.toml contains placeholders only.
4. Remove obsolete hosted `db_path` settings to make backend selection unambiguous. An explicit
   `database_url` takes priority. Environment-only configuration uses `FLEETCARE_DATABASE_URL` and optional
   `FLEETCARE_DATABASE_SCHEMA`. Explicit local SQLite paths remain useful for tests/offline tools.
5. Review/merge the code before restarting Streamlit. Saving hosting secrets or merging main may redeploy
   the app. Those live actions require Enamul's review; do not switch the hosted branch to a test branch.

## Acceptance after the reviewed cutover

- Confirm the sidebar says **Saved history uses PostgreSQL storage**.
- Create one order as admin; sign in as the assigned customer in a second session and respond.
- Sign out/in, choose Completed/Rejected or View all saved orders; verify the response is retained.
- Refresh the admin's same fault; verify exact feedback and unchanged evidence-derived fault status.
- Restart the application and repeat the read. PostgreSQL data must remain present without reseeding work.
- A missing/unreachable/invalid PostgreSQL configuration must show an error, not a fresh SQLite queue.
- A temporary compute pause can add connection latency. Reads reconnect; uncertain writes require refresh
  before an explicit idempotent retry. Do not reset the database to work around an error.

## Existing data and limits

No existing SQLite file is deleted or automatically moved to PostgreSQL. Preserve any still-readable
records before cutover. Review their source and assignment before a separate import; do not blindly copy
sessions or overwrite terminal responses. Data already lost from a replaced Streamlit filesystem is not
restored by selecting PostgreSQL. The prepared fleet dataset is reproducible; customer responses are not.

Free-plan quotas/restore retention and account availability still apply. Storage survives Streamlit
restarts, but this is not an unlimited-storage guarantee, backup policy or production SLA. Never delete
or reset the production branch as a troubleshooting step. Select and test exports/backups before storing
important data. Public synthetic demo accounts remain intentionally public; private credential mapping
can still be supplied through the existing configuration for a restricted review.
