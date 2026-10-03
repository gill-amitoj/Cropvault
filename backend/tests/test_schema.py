import psycopg
import pytest

from app import db


def insert_user(conn, email="r@example.com", role="researcher"):
    return conn.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (%s, 'x', %s) RETURNING id",
        (email, role),
    ).fetchone()[0]


def insert_image(conn, user_id, sha="a" * 64, parent_image_id=None, derivation=None):
    return conn.execute(
        """
        INSERT INTO images (original_filename, storage_key, content_type, size_bytes,
                            width, height, sha256, uploaded_by, parent_image_id, derivation,
                            capture_date)
        VALUES ('leaf.jpg', %s, 'image/jpeg', 100, 10, 10, %s, %s, %s, %s, '2026-05-01')
        RETURNING id
        """,
        (f"originals/{sha}", sha, user_id, parent_image_id, derivation),
    ).fetchone()[0]


def test_apply_schema_is_idempotent_and_seeds_experiments(clean_db):
    db.apply_schema()
    db.apply_schema()
    with db.get_connection() as conn:
        codes = [r[0] for r in conn.execute("SELECT code FROM experiments ORDER BY code")]
    assert codes == ["EXP-2026-001", "EXP-2026-002"]


def test_duplicate_sha256_is_rejected(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
        insert_image(conn, user_id, sha="b" * 64)
    with pytest.raises(psycopg.errors.UniqueViolation), db.get_connection() as conn:
        conn.execute(
            """INSERT INTO images (original_filename, storage_key, content_type, size_bytes,
                                   width, height, sha256, uploaded_by)
               VALUES ('copy.jpg', 'other-key', 'image/jpeg', 100, 10, 10, %s, %s)""",
            ("b" * 64, user_id),
        )


def test_invalid_role_is_rejected(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        insert_user(conn, role="superuser")


def test_uppercase_email_is_rejected(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        insert_user(conn, email="Admin@Example.com")


def test_invalid_derivation_is_rejected(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
        parent_id = insert_image(conn, user_id)
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        insert_image(conn, user_id, sha="c" * 64, parent_image_id=parent_id, derivation="blur")


def test_derived_image_needs_a_parent(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        insert_image(conn, user_id, derivation="crop")


def test_original_cannot_be_deleted_while_crops_exist(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
        parent_id = insert_image(conn, user_id)
        insert_image(conn, user_id, sha="d" * 64, parent_image_id=parent_id, derivation="crop")
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.get_connection() as conn:
        conn.execute("DELETE FROM images WHERE id = %s", (parent_id,))


def test_deleting_image_deletes_its_annotations(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
        image_id = insert_image(conn, user_id)
        conn.execute(
            """INSERT INTO annotations (image_id, label, kind, geometry, created_by)
               VALUES (%s, 'lesion', 'bbox', '{"x":0.1,"y":0.1,"w":0.2,"h":0.2}', %s)""",
            (image_id, user_id),
        )
        conn.execute("DELETE FROM images WHERE id = %s", (image_id,))
        count = conn.execute("SELECT count(*) FROM annotations").fetchone()[0]
    assert count == 0


def test_invalid_annotation_kind_is_rejected(clean_db):
    with db.get_connection() as conn:
        user_id = insert_user(conn)
        image_id = insert_image(conn, user_id)
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        conn.execute(
            """INSERT INTO annotations (image_id, label, kind, geometry, created_by)
               VALUES (%s, 'lesion', 'circle', '{}', %s)""",
            (image_id, user_id),
        )


def test_invalid_audit_action_is_rejected(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation), db.get_connection() as conn:
        conn.execute("INSERT INTO audit_log (action, entity_type) VALUES ('HACK', 'image')")


def test_capture_date_is_a_date_column(clean_db):
    with db.get_connection() as conn:
        data_type = conn.execute(
            """SELECT data_type FROM information_schema.columns
               WHERE table_name = 'images' AND column_name = 'capture_date'"""
        ).fetchone()[0]
    assert data_type == "date"
