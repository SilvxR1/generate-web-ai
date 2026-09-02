import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.domain.enums import UserRole


class UserBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: UserRole = UserRole.OPERATOR


class UserCreate(UserBase):
    tenant_id: uuid.UUID


class UserRead(UserBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
