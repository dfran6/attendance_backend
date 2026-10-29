"""Bootstrap the first administrative area, CDS group and super-admin account.

Registration can never grant admin roles, so the first super admin is created here:

    python -m src.scripts.bootstrap --email admin@example.gov.ng --name "Ada LGI" \
        --state-code LA/24A/0001 --area-name "Ikeja" --area-code IKJ --state Lagos \
        --group-name "Health" --group-code IKJ-HEALTH

        python -m src.scripts.bootstrap --email ronaldewherhe21@gmail.com --name "Ronald LGI" \
                --state-code LA/24A/0001 --area-name "Eti-osa 3" --area-code Eti --state Lagos \
                --group-name "Health" --group-code IKJ-HEALTH

The password is read interactively (never pass it on the command line). Idempotent: existing
rows matched by email / code are reused.
"""
import argparse
import asyncio
import getpass

from sqlmodel import select

from src.core.security import hash_password
from src.db.mains import AsyncSessionLocal
from src.models import AdminArea, CdsGroup, RoleAssignment, User
from src.models.enums import AccountStatus, AdminRole
from src.modules.audit import service as audit
from src.modules.auth.schema import check_password_strength, normalize_email, normalize_state_code


async def main(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as s:
        area = (await s.exec(select(AdminArea).where(AdminArea.code == args.area_code.upper()))).first()
        if area is None:
            area = AdminArea(name=args.area_name, code=args.area_code.upper(), state=args.state)
            s.add(area)
            await s.flush()
            print(f"Created area {area.name} ({area.code})")

        if args.group_name:
            code = args.group_code.upper()
            group = (await s.exec(select(CdsGroup).where(CdsGroup.code == code))).first()
            if group is None:
                s.add(CdsGroup(area_id=area.id, name=args.group_name, code=code))
                print(f"Created group {args.group_name} ({code})")

        email = normalize_email(args.email)
        user = (await s.exec(select(User).where(User.email == email))).first()
        if user is None:
            password = getpass.getpass("Password for the super admin: ")
            check_password_strength(password)
            user = User(full_name=args.name, email=email, state_code=normalize_state_code(args.state_code),
                        password_hash=hash_password(password), account_status=AccountStatus.approved)
            s.add(user)
            await s.flush()
            print(f"Created user {email}")

        has_role = (
            await s.exec(select(RoleAssignment).where(RoleAssignment.user_id == user.id,
                                                      RoleAssignment.role == AdminRole.super_admin,
                                                      RoleAssignment.revoked_at.is_(None)))
        ).first()
        if has_role is None:
            s.add(RoleAssignment(user_id=user.id, role=AdminRole.super_admin))
            audit.record(s, "role.granted", target_type="user", target_id=user.id,
                         context={"role": "super_admin", "via": "bootstrap"})
            print("Granted super_admin")
        await s.commit()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--state-code", required=True)
    p.add_argument("--area-name", required=True)
    p.add_argument("--area-code", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--group-name")
    p.add_argument("--group-code")
    asyncio.run(main(p.parse_args()))
