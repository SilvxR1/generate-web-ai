"""NotificationSender — the email-provider-neutral interface between an
internal notification that needs delivering and whatever actually sends
it. SmtpNotificationSender (app.notifications.smtp) is the first,
replaceable implementation; nothing outside app.notifications.smtp
should need to know SMTP (or any specific provider like Resend/Postmark)
exists. Mirrors app.publishing.publisher.WebsitePublisher's shape for
the publishing side of this codebase.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, EmailStr, TypeAdapter, ValidationError

_EMAIL_ADAPTER: TypeAdapter[str] = TypeAdapter(EmailStr)


def safe_reply_to(value: object) -> str | None:
    """`value` as a bare, validated address fit for a Reply-To header, or
    None when it's missing or not one. A bad stored address (lead emails
    reaching /internal/leads are plain strings) must never block the
    email itself, so this never raises — the message just goes out
    without a Reply-To. Rejects anything with whitespace or control
    characters before EmailStr even sees it: a CR/LF in a header value
    is header injection, and "Name <addr>" display forms aren't needed."""
    if not isinstance(value, str) or not value or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    try:
        return _EMAIL_ADAPTER.validate_python(value)
    except ValidationError:
        return None


class NotificationEmail(BaseModel):
    """A single outbound notification email — provider-neutral (no SMTP,
    Resend, or Postmark-specific fields). Plain text only: internal
    lead-notification copy doesn't need HTML/attachments yet.

    `reply_to` is where a reply should go when that isn't the From
    address (which is the platform's shared sending domain, not the
    business's own inbox). Callers build it with safe_reply_to."""

    model_config = ConfigDict(extra="forbid")

    to: EmailStr
    subject: str
    body: str
    reply_to: EmailStr | None = None


class NotificationSender(ABC):
    @abstractmethod
    def send(self, message: NotificationEmail) -> None:
        """Delivers `message` or raises NotificationSenderError — never
        silently swallows a failure into a fake success."""
        ...
