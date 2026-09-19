"""Every DateTime column in this app must be timezone-aware.

Found via `alembic check` against a real PostgreSQL instance:
ScriptVersion.created_at was declared as a bare `DateTime()` while the
actual deployed column (from the initial migration) is TIMESTAMPTZ, like
every other datetime column in the schema — a plain oversight, not a
deliberate choice; the whole app works in UTC-aware datetimes
(datetime.now(UTC) everywhere). Left alone, autogenerate would propose
"fixing" the real column back to a naive TIMESTAMP, and any tool that
gates deploys on `alembic check` would fail on a column that was actually
fine. This test catches the same mistake on any future model without
needing a live Postgres connection.
"""

from sqlalchemy import DateTime

from app.database import Base


def test_all_datetime_columns_are_timezone_aware():
    offenders = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime) and not column.type.timezone:
                offenders.append(f"{table.name}.{column.name}")

    assert not offenders, (
        "DateTime column(s) missing timezone=True (inconsistent with the "
        f"rest of the schema, which is TIMESTAMPTZ everywhere): {offenders}"
    )
