class WebsitePublisherError(Exception):
    """Base for every error a WebsitePublisher implementation raises —
    the type a caller depending on WebsitePublisher (not on any specific
    hosting provider) should catch. Mirrors
    app.automation.errors.AutomationEngineError's role for AutomationEngine.
    """
