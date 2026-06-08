"""Admin route aggregator.

Each resource lives in its own module (``users``, ``activities``) and is mounted
here so ``api/main.py`` only needs to import a single ``router``.
"""

from fastapi import APIRouter

from app.api.routes.admin import activities, admins, files, stats, support, users

router = APIRouter()
router.include_router(users.router, prefix="/users")
router.include_router(admins.router, prefix="/admins")
router.include_router(files.router, prefix="/files")
router.include_router(support.router, prefix="/support")
router.include_router(activities.router)
router.include_router(stats.router)
