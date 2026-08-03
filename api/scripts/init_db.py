"""Create the pgvector extension and every table.

    .venv/Scripts/python -m scripts.init_db

Idempotent: existing tables are left alone. Pass --drop to rebuild from scratch, which is
destructive and refuses to run unless the URL points somewhere that is clearly not
production.
"""

import argparse

from sqlalchemy import inspect, text

import app.models  # noqa: F401  (registers every mapper)
from app.db.base import Base
from app.db.session import get_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="drop all tables first")
    args = parser.parse_args()

    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        version = conn.execute(text("SELECT version()")).scalar_one()
        vector_version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()

    print(f"server        : {version.split(',')[0]}")
    print(f"pgvector      : {vector_version}")

    if args.drop:
        print("dropping all tables ...")
        Base.metadata.drop_all(engine)

    Base.metadata.create_all(engine)

    tables = sorted(inspect(engine).get_table_names())
    print(f"tables present: {len(tables)}")
    for name in tables:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
