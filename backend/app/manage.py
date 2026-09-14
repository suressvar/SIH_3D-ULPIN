"""Administrator-only local CLI. No public role-granting endpoint."""

import argparse
from uuid import UUID

from app.db import get_session
from app.models import AppUser
from app.repositories import audit

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register an existing Supabase user in the private application membership table"
    )
    parser.add_argument("user_id", type=UUID, help="Verified Supabase Auth user UUID")
    parser.add_argument("role", choices=["viewer", "surveyor", "officer", "admin"])
    args = parser.parse_args()
    with get_session() as db, db.begin():
        user = db.get(AppUser, args.user_id)
        if user:
            user.role, user.active = args.role, True
        else:
            user = AppUser(id=args.user_id, role=args.role, active=True)
            db.add(user)
        audit(
            db,
            user.id,
            "MEMBERSHIP_PROVISIONED_BY_ADMIN_CLI",
            user,
            {"role": args.role},
        )
    print(
        "Membership provisioned. Sign in through Supabase Auth to obtain an access token."
    )
