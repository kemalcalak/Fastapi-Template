"""Admin route aggregator.

Each resource lives in its own module (``users``, ``activities``) and is mounted
here so ``api/main.py`` only needs to import a single ``router``.
"""

from fastapi import APIRouter

from app.api.routes.admin import activities, users

router = APIRouter()
router.include_router(users.router, prefix="/users")
router.include_router(activities.router)
