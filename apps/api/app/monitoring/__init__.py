"""Website Health / monitoring (P1.4-P1.5): reusable HTTP/DNS/TLS/form
checks (app.monitoring.checks) orchestrated per-business
(app.monitoring.service) into one WebsiteHealthCheck snapshot
(app.db.models.website_health). Deliberately NOT bound to any scheduler
(n8n, cron, a worker) — app.routers.website_health exposes a plain
POST .../website-health/check any of those can call; the check logic
itself knows nothing about who or what triggers it."""
