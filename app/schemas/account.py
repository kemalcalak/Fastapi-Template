from enum import StrEnum

from pydantic import BaseModel


class AccountEventType(StrEnum):
    """Realtime event types pushed to a single user's account socket."""

    PERMISSIONS_UPDATED = "permissions_updated"
    # One or more of the user's sessions were revoked (remote logout, admin
    # kill, password change). Clients re-validate their own session and drop
    # to the login screen if it was theirs.
    SESSIONS_REVOKED = "sessions_revoked"


class AccountEvent(BaseModel):
    """A realtime notification delivered to one user's account channel.

    Intentionally minimal: the client treats it as a signal to refetch the
    affected state (e.g. ``GET /users/me`` after ``permissions_updated``) rather
    than trusting a pushed payload.
    """

    type: AccountEventType
