class NotificationSenderError(Exception):
    """Base for every error a NotificationSender implementation raises —
    the type a caller depending on NotificationSender (not on any
    specific email provider) should catch. Mirrors
    app.publishing.errors.WebsitePublisherError's role for
    WebsitePublisher.
    """
