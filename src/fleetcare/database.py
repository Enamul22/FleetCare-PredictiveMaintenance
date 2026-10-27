"""Offline PostgreSQL schema migration. Never changes the live app's hosting configuration."""

import argparse
import getpass
import os
from urllib.parse import urlsplit
from psycopg import sql
from .config import ROOT
from .storage import PostgresStore, StorageError, validate_url


def migrate(url, schema="fleetcare"):
    validate_url(url)
    if "-pooler" in (urlsplit(url).hostname or ""):
        raise StorageError("Schema migration requires the direct (unpooled) database connection.")
    db = PostgresStore(url, schema)
    try:
        with db.transaction():
            db.connection.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(schema)))
            tables = db.tables()
            if "store_meta" in tables:
                version = db.execute("select value from store_meta where key='schema_pg'").fetchone()
                if not version or version[0] != "1":
                    raise StorageError("Unknown PostgreSQL schema revision; refusing to overwrite it.")
            elif tables:
                raise StorageError(
                    "Selected schema contains unrelated tables. Choose an empty FleetCare schema."
                )
            script = (ROOT / "migrations/001_postgres.sql").read_text()
            for statement in script.split(";"):
                if statement.strip():
                    db.connection.execute(statement)
            db.execute("insert into store_meta values ('schema_pg','1') on conflict(key) do nothing")
            db.execute("insert into store_meta values ('schema_r2','2') on conflict(key) do nothing")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Initialize/verify FleetCare PostgreSQL schema using a direct TLS connection"
    )
    parser.add_argument(
        "--url-env",
        default="FLEETCARE_DATABASE_URL_DIRECT",
        help="Name of the environment variable containing the private direct URL",
    )
    parser.add_argument("--schema", default="fleetcare")
    parser.add_argument(
        "--prompt", action="store_true", help="Read the direct URL from a hidden interactive prompt"
    )
    parser.add_argument(
        "--seed", action="store_true", help="Import prepared reference data; does not create work orders"
    )
    args = parser.parse_args()
    url = getpass.getpass("Direct PostgreSQL URL (hidden): ") if args.prompt else os.environ.get(args.url_env)
    if not url:
        parser.error(
            f"Set {args.url_env} privately first; do not pass a connection string on the command line"
        )
    try:
        migrate(url, args.schema)
        if args.seed:
            from .service import Service

            svc = Service(database_url=url, database_schema=args.schema)
            svc.db.close()
        print(
            f"FleetCare PostgreSQL schema {args.schema}: migration complete. No orders or responses were reset."
        )
    except (StorageError, OSError):
        parser.exit(
            1,
            "Database initialization failed. Check the direct TLS connection, schema ownership and migration revision. Connection details have not been printed.\n",
        )


if __name__ == "__main__":
    main()
