from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    email: str | None
    enabled: bool


class AuthMeResponse(BaseModel):
    data: UserProfile
