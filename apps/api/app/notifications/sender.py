"""NotificationSender — the email-provider-neutral interface between an
internal notification that needs delivering and whatever actually sends
it. SmtpNotificationSender (app.notifications.smtp) is the first,
replaceable implementation; nothing outside app.notifications.smtp
should need to know SMTP (or any specific provider like Resend/Postmark)
exists. Mirrors app.publishing.publisher.WebsitePublisher's shape for
the publishing side of this codebase.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, EmailStr


class NotificationEmail(BaseModel):
    """A single outbound notification email — provider-neutral (no SMTP,
    Resend, or Postmark-specific fields). Plain text only: internal
    lead-notification copy doesn't need HTML/attachments yet."""

    model_config = ConfigDict(extra="forbid")

    to: EmailStr
    subject: str
    body: str


class NotificationSender(ABC):
    @abstractmethod
    def send(self, message: NotificationEmail) -> None:
        """Delivers `message` or raises NotificationSenderError — never
        silently swallows a failure into a fake success."""
        ...
