from pydantic import BaseModel

LOCAL_USER_ID = "local-user"


class User(BaseModel):
    id: str
