"""is_spam — the boundary the public lead endpoint checks before ever
persisting a submission (Phase 8). Two cheap, well-known heuristics
today: a honeypot field and a minimum time-on-form; both are boundaries a
real future CAPTCHA/provider check (reCAPTCHA, Turnstile, ...) would slot
into the same call site without this function's own signature needing to
change — see app.routers.public for where that would go.
"""

from datetime import datetime, timedelta

DEFAULT_MIN_SUBMIT_SECONDS = 2.0


def is_spam(
    *,
    honeypot_value: str,
    rendered_at: datetime | None,
    now: datetime,
    min_submit_seconds: float = DEFAULT_MIN_SUBMIT_SECONDS,
) -> bool:
    """True if either check fires:

    - `honeypot_value` is non-empty — a field the real form renders
      visually hidden; only an automated submitter fills every field.
    - `rendered_at` is set and less than `min_submit_seconds` before
      `now` — faster than a human could plausibly read and fill the
      form. `rendered_at` being absent (a client that doesn't send it)
      is never itself treated as spam — only an *impossibly fast* real
      timestamp is.
    """
    if honeypot_value.strip():
        return True
    if rendered_at is not None and now - rendered_at < timedelta(seconds=min_submit_seconds):
        return True
    return False
