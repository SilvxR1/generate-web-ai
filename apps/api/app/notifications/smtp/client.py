"""SmtpNotificationSender — the first, replaceable NotificationSender
implementation. SMTP rather than a specific transactional-email vendor
(Resend, Postmark, ...) on purpose: any real provider can be reached
through it by pointing `host`/`port`/`username`/`password` at that
provider's SMTP endpoint, so choosing a vendor later is an operator
decision (which SMTP credentials to configure), never a code change
here or anywhere depending on NotificationSender.
"""

import smtplib
from email.message import EmailMessage as MimeEmailMessage

from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender


class SmtpNotificationSender(NotificationSender):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from_address = from_address
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout

    def send(self, message: NotificationEmail) -> None:
        mime_message = MimeEmailMessage()
        mime_message["From"] = self._from_address
        mime_message["To"] = message.to
        mime_message["Subject"] = message.subject
        mime_message.set_content(message.body)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as connection:
                if self._use_tls:
                    connection.starttls()
                if self._username and self._password:
                    connection.login(self._username, self._password)
                connection.send_message(mime_message)
        except (smtplib.SMTPException, OSError) as exc:
            # Never includes `self._password` — smtplib's own exceptions
            # carry the server's response text, not our credentials.
            raise NotificationSenderError(f"SMTP delivery failed: {exc}") from exc
