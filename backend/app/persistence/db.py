import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def database(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./meditron.db")
    engine = create_engine(url, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def setup(connection, _):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")

        @event.listens_for(engine, "begin")
        def begin(connection):
            # SQLite is only the local demo/test fallback. Serialize write transactions.
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine, sessionmaker(engine, expire_on_commit=False)
