import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# No CredentialBase shared between Create and Read: Create carries a
# plaintext `secret` (encrypted immediately by CredentialService, never
# persisted as-is); Read deliberately has no secret/encrypted_value field
# at all, so a decrypted or encrypted value can never leave via this
# schema by accident, even if a future endpoint naively returns the ORM
# object through it.


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID
    integration_id: uuid.UUID
    secret: str = Field(min_length=1)
    expires_at: datetime | None = None


class CredentialRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    integration_id: uuid.UUID
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
