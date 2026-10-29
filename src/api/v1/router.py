from fastapi import APIRouter

from src.modules.attendance.routes import attendance_router, session_attendance_router
from src.modules.auth.routes import auth_router
from src.modules.groups.routes import area_router, group_router
from src.modules.memberships.routes import membership_router
from src.modules.sessions.routes import session_router
from src.modules.users.routes import user_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(user_router, prefix="/users", tags=["Users"])
api_router.include_router(area_router, prefix="/areas", tags=["Administrative areas"])
api_router.include_router(group_router, prefix="/groups", tags=["Groups"])
api_router.include_router(membership_router, tags=["Memberships"])
api_router.include_router(session_router, prefix="/sessions", tags=["Sessions"])
api_router.include_router(session_attendance_router, prefix="/sessions", tags=["Attendance"])
api_router.include_router(attendance_router, prefix="/attendance", tags=["Attendance"])

# Planned (phases 5–7): excuses, reports, audit, moderators.
