from fastapi import APIRouter

from app.api.routes import admin, auth, files, health, notifications, support, users

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
api_router.include_router(support.router, prefix="/support", tags=["support"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(files.router, tags=["files"])
