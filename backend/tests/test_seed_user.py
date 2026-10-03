from argon2 import PasswordHasher

from app import db


def get_users():
    with db.get_connection() as conn:
        return conn.execute("SELECT email, password_hash, role FROM users").fetchall()


def test_seed_admin_creates_admin_with_argon2_hash(clean_db):
    db.seed_user("Admin@Example.com", "s3cret-pass", "admin")

    [user] = get_users()
    email, password_hash, role = user["email"], user["password_hash"], user["role"]
    assert email == "admin@example.com"
    assert role == "admin"
    assert password_hash != "s3cret-pass"
    assert password_hash.startswith("$argon2")
    assert PasswordHasher().verify(password_hash, "s3cret-pass")


def test_seed_user_twice_creates_one_user_and_keeps_password_and_role(clean_db):
    db.seed_user("admin@example.com", "first-password", "admin")
    first_hash = get_users()[0]["password_hash"]

    db.seed_user("admin@example.com", "changed-in-env", "researcher")

    users = get_users()
    assert len(users) == 1
    assert users[0]["password_hash"] == first_hash
    assert users[0]["role"] == "admin"  # role not overwritten either


def test_seed_user_creates_ingest_researcher(clean_db):
    db.seed_user("ingest@example.com", "ingest-password", "researcher")
    [user] = get_users()
    assert (user["email"], user["role"]) == ("ingest@example.com", "researcher")
