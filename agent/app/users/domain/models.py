from pydantic import BaseModel

# No auth system exists yet (local dev tool, single user) — every session/attempt
# is attributed to this fixed id until real auth is worth building.
LOCAL_USER_ID = "local-user"


class User(BaseModel):
    id: str
