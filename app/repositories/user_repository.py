from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.repositories.session import connect


def create_user(email: str, hashed_password: str, full_name: str | None = None) -> dict[str, Any]:
    user_id = uuid4()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, hashed_password, full_name, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id, email, full_name, created_at
                """,
                (user_id, email.lower().strip(), hashed_password, full_name),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, email, hashed_password, full_name, created_at
            FROM users
            WHERE email = %s
            """,
            (email.lower().strip(),),
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "hashed_password": row["hashed_password"],
        "full_name": row["full_name"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def get_user_by_id(user_id: UUID | str) -> dict[str, Any] | None:
    try:
        uid = UUID(str(user_id))
    except ValueError:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, email, hashed_password, full_name, created_at
            FROM users
            WHERE id = %s
            """,
            (uid,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "hashed_password": row["hashed_password"],
        "full_name": row["full_name"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def delete_user(user_id: UUID) -> bool:
    """Delete a user. WARNING: This cascades to all user's documents."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
