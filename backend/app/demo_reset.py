"""Clear only the dedicated PostgreSQL database used by Docker Compose demos."""

import os

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.persistence.models import Base, Case


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if (
        os.getenv("MEDITRON_DEMO_RESET") != "compose"
        or not url.drivername.startswith("postgresql")
        or url.host != "db"
        or url.database != "meditron"
        or url.username != "meditron"
    ):
        raise SystemExit("Сброс разрешён только для базы демонстрационного Docker Compose")

    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.tables.values())
    engine = create_engine(url)
    with engine.begin() as connection:
        old_cases = connection.scalar(select(func.count()).select_from(Case))
        connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    engine.dispose()
    print(f"Удалено {old_cases} прежних случаев; база готова к новому набору")


if __name__ == "__main__":
    main()
