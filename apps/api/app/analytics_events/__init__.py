"""Consent-gated business analytics (P1.7/P1.8): AnalyticsProvider
(app.analytics_events.provider) is the swappable ingestion boundary — an
InternalAnalyticsProvider persisting to app.db.models.analytics_event is
the only implementation today, chosen specifically so this codebase
never takes on an external analytics SaaS dependency for the first
version (a future Plausible/Cloudflare Web Analytics/GA provider would
implement the same interface). app.analytics_events.metrics aggregates
those events (plus the authoritative Lead table for real conversions)
into the numbers app.routers.analytics and Studio's Business Metrics
panel read.
"""
