from __future__ import annotations

from importlib import resources

from .config import Settings, load_settings
from .db import connect


def migrate(settings: Settings | None = None) -> list[str]:
    resolved = settings or load_settings()
    applied: list[str] = []
    sql_files = sorted(resources.files("llm_wiki").joinpath("migrations").iterdir())
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                  version text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            for sql_file in sql_files:
                if not sql_file.name.endswith(".sql"):
                    continue
                cur.execute("select 1 from schema_migrations where version = %s", (sql_file.name,))
                if cur.fetchone():
                    continue
                cur.execute(sql_file.read_text(encoding="utf-8"))
                cur.execute("insert into schema_migrations (version) values (%s)", (sql_file.name,))
                applied.append(sql_file.name)
        conn.commit()
    return applied
