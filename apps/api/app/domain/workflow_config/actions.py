"""The closed action catalog. This IS the security boundary the brief
asks for, not an afterthought bolted on:

- No `code.execute`/`shell.run`/`python.eval`-style action exists, so
  arbitrary code/shell/Python execution is impossible *by construction*
  — there is nothing to validate against because there is no such
  action to select.
- Every action but `http.request` has a fully closed, `extra="forbid"`
  inputs shape with no free-form field a secret could be smuggled into.
- `http.request` is the one action with a free-form `headers` dict and a
  caller-supplied `url` — the only place credential-shaped content could
  actually appear — so that's the one place with an explicit validator
  (`_reject_secret_like_keys` / the `url` validator below).

Nothing here ever holds a real secret value: `EmailSendInputs.to` is a
role (`customer`/`business_owner`), never a literal address; a real
integration's credential lives on the existing `Credential` entity
(app.db.models.credential), a different bounded context this module
never reaches into.
"""

import re
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SECRET_LIKE = re.compile(
    r"(password|secret|token|api[-_]?key|apikey|credential|private[-_]?key|client[-_]?secret|access[-_]?key|authorization)",
    re.IGNORECASE,
)


def _reject_secret_like_keys(keys: list[str], where: str) -> None:
    for key in keys:
        if _SECRET_LIKE.search(key):
            raise ValueError(
                f"{where} key {key!r} looks like a credential or secret. Workflows never embed credentials — "
                "reference an Integration/Credential by id once that wiring exists, not here."
            )


class ActionType(StrEnum):
    LEAD_STORE = "lead.store"
    LEAD_LOOKUP = "lead.lookup"
    LEAD_FOLLOW_UP_EMAIL = "lead.follow_up_email"
    EMAIL_SEND = "email.send"
    NOTIFICATION_SEND = "notification.send"
    HTTP_REQUEST = "http.request"
    WAIT = "wait"


class EmailRecipient(StrEnum):
    """A role, never a literal address — the future AutomationEngine
    resolves this against the triggering event/business, not this
    config."""

    CUSTOMER = "customer"
    BUSINESS_OWNER = "business_owner"


class LeadStoreInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.LEAD_STORE] = ActionType.LEAD_STORE


class LeadLookupInputs(BaseModel):
    """Fetches one lead's *current* state — the fresh read a follow-up
    condition needs after a wait, as opposed to whatever data was known
    when the lead was first stored. Same minimal shape as
    LeadStoreInputs (no fields beyond the discriminator): which lead and
    which tenant/business is runtime data (the id lead.store returned,
    resolved by the future AutomationEngine/translator), never something
    this config carries."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.LEAD_LOOKUP] = ActionType.LEAD_LOOKUP


class LeadFollowUpEmailInputs(BaseModel):
    """Sends a real, provider-neutral email *to the lead itself* — never
    represented as an InternalNotification (that model means "the
    business's own team was told about something", a different concept
    this action deliberately stays clear of). No recipient here: it's
    resolved server-side from the lead's own current row (see
    app.routers.internal_automation's follow-up-email endpoint), the
    same "runtime data, not config" reasoning as LeadLookupInputs above.
    `template` mirrors NotificationSendInputs.template — a named id,
    unused by the translator today (content is a fixed, safe, business-
    name-based message for this MVP; no per-template dynamic generation
    yet), kept for the same forward-compatibility reason."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.LEAD_FOLLOW_UP_EMAIL] = ActionType.LEAD_FOLLOW_UP_EMAIL
    template: str = Field(min_length=1, max_length=100)


class EmailSendInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.EMAIL_SEND] = ActionType.EMAIL_SEND
    to: EmailRecipient
    # A named template id, not the message body — copywriting is a
    # future/human concern, not something this config carries.
    template: str = Field(min_length=1, max_length=100)
    subject: str | None = Field(default=None, max_length=200)


class NotificationSendInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.NOTIFICATION_SEND] = ActionType.NOTIFICATION_SEND
    template: str = Field(min_length=1, max_length=100)


class WaitInputs(BaseModel):
    """Pauses the workflow for a fixed duration before continuing —
    e.g. the gap between "notify the business" and "check whether the
    lead was contacted yet" in a follow-up sequence. A plain delay only:
    no "resume on webhook"/"resume at specific time" mode, since nothing
    in this codebase needs those yet."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.WAIT] = ActionType.WAIT
    hours: int = Field(gt=0, le=720)


class HttpRequestInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[ActionType.HTTP_REQUEST] = ActionType.HTTP_REQUEST
    url: str = Field(min_length=1, max_length=2048)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    # A named template id for the body, same reasoning as EmailSendInputs.template.
    body_template: str | None = Field(default=None, max_length=100)

    @field_validator("headers")
    @classmethod
    def _no_secret_headers(cls, value: dict[str, str]) -> dict[str, str]:
        _reject_secret_like_keys(list(value.keys()), "header")
        return value

    @field_validator("url")
    @classmethod
    def _no_secret_query_params(cls, value: str) -> str:
        query = urlsplit(value).query
        _reject_secret_like_keys(list(parse_qs(query).keys()), "URL query parameter")
        return value


ActionInputs = Annotated[
    LeadStoreInputs
    | LeadLookupInputs
    | LeadFollowUpEmailInputs
    | EmailSendInputs
    | NotificationSendInputs
    | HttpRequestInputs
    | WaitInputs,
    Field(discriminator="action"),
]
