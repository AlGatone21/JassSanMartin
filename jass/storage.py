"""Small durable document store shared by SQLite and PostgreSQL deployments."""
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock

from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, select


class Store:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url in ("sqlite://", "sqlite:///:memory:"):
                from sqlalchemy.pool import StaticPool
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.lock = RLock()
        metadata = MetaData()
        self.records = Table(
            "records", metadata,
            Column("id", String(32), primary_key=True),
            Column("kind", String(24), nullable=False, index=True),
            Column("owner", String(64), nullable=False, index=True),
            Column("updated", String(40), nullable=False),
            Column("data", JSON, nullable=False),
        )
        metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        # One Gunicorn worker, several threads: serialize read-modify-write cycles.
        with self.lock, self.engine.begin() as connection:
            yield connection

    def get(self, connection, record_id, kind=None):
        query = select(self.records).where(self.records.c.id == record_id)
        if kind:
            query = query.where(self.records.c.kind == kind)
        row = connection.execute(query).mappings().first()
        return dict(row) if row else None

    def put(self, connection, record_id, kind, owner, data, new=False):
        values = dict(kind=kind, owner=owner, data=data,
                      updated=datetime.now(timezone.utc).isoformat())
        if new:
            connection.execute(self.records.insert().values(id=record_id, **values))
        else:
            connection.execute(self.records.update().where(self.records.c.id == record_id).values(**values))

    def all(self, connection):
        return [dict(row) for row in connection.execute(
            select(self.records).order_by(self.records.c.updated.desc())
        ).mappings()]
