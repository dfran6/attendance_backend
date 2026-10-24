from fastapi import FastAPI
from src.modules.auth.routes import auth_router
from src.modules.users.routes import user_router
from src.modules.groups.routes import group_router
from src.modules.moderators.routes import moderator_router
from src.modules.registration.routes import registration_router
from src.modules.attendance import attendance_router
from src.modules.sessions.routes import session_router
from src.modules.audit.routes import audit_router
from src.modules.reports.routes import report_router
from src.modules.excuses.routes import excuse_router


version = "v1"

app = FastAPI(
    title = "Nysc Attendance app",
    summary = "an attendance app for making attendance taking more efficient ",
    version = version
)

@app.get("")
async def welcome():
    return {"message":"Welcome to our attendance app."}

app.include_router(auth_router, prefix=f"/api/{version}/auth", tags=["Authentication"])
app.include_router(user_router, prefix=f"/api/{version}/auth", tags=["Users"])
app.include_router(group_router, prefix=f"/api/{version}/auth", tags=["Groups"])
app.include_router(moderator_router, prefix=f"/api/{version}/auth", tags=["Moderators"])
app.include_router(registration_router, prefix=f"/api/{version}/auth", tags=["Registrations"])
app.include_router(attendance_router, prefix=f"/api/{version}/auth", tags=["Attendance"])
app.include_router(session_router, prefix=f"/api/{version}/auth", tags=["Sessions"])
app.include_router(audit_router, prefix=f"/api/{version}/auth", tags=["Audits"])
app.include_router(report_router, prefix=f"/api/{version}/auth", tags=["Reports"])
app.include_router(excuse_router, prefix=f"/api/{version}/auth", tags=["Excuses"])
    