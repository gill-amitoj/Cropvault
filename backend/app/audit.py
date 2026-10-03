"""Audit log writes. Pass the same connection as the change being audited, so the change
and its audit row are committed together (or not at all)."""

from psycopg.types.json import Jsonb


def write_audit(conn, user_id, action, entity_type, entity_id=None, details=None) -> None:
    conn.execute(
        """INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
           VALUES (%s, %s, %s, %s, %s)""",
        (user_id, action, entity_type, entity_id, Jsonb(details) if details else None),
    )
