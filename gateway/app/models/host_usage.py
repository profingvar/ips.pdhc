"""Per-(host, caller) request counter for the eps rename (#1017).

Phase 4 of epic #1015 may only retire ``ips.pdhc.se`` once no caller uses
it. This table is the evidence: one row per (Host header, caller identity),
with a count and first/last seen. Additive -- a new table, nothing else
changes; ``db.create_all()`` creates it, and
``migrations/add_host_usage.sql`` does the same idempotently on prod.

The identity is NEVER a secret: an API key's row guid and label, a read
grant's partner guid, a bearer's SSO ``user_type``, or the scheme of a
credential that was refused. No token, no key, no key prefix, no user.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import db, utcnow


class HostUsage(db.Model):
    __tablename__ = "host_usage"

    host: Mapped[str] = mapped_column(String(255), primary_key=True)
    caller_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    caller_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    caller_label: Mapped[str | None] = mapped_column(String(255))
    count: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, default=0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow)
