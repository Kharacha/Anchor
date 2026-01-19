# apps/api/app/repos/user_settings_repo.py

from sqlalchemy import text


def get_user_settings_flags(conn, user_id: str) -> tuple[bool, bool]:
    """
    Returns (personalization_opt_in, baseline_opt_in).
    If no row exists, returns (False, False).
    """
    row = conn.execute(
        text("""
            select personalization_opt_in, baseline_opt_in
            from user_settings
            where user_id = cast(:user_id as uuid)
            limit 1
        """),
        {"user_id": user_id},
    ).first()

    if not row:
        return False, False

    return bool(row[0]), bool(row[1])


def ensure_user_settings_row(conn, user_id: str) -> None:
    """
    Creates a user_settings row if missing (defaults apply).
    Safe to call any time.
    """
    conn.execute(
        text("""
            insert into user_settings (user_id)
            values (cast(:user_id as uuid))
            on conflict (user_id) do nothing
        """),
        {"user_id": user_id},
    )
