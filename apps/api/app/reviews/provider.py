"""ReviewProvider — the provider-neutral honest-availability interface
for P1.6's review sources, mirroring app.creative.provider.CreativeProvider's
shape (an ABC plus swappable concrete implementations,
app.dependencies-style factory functions per provider).

Deliberately minimal: neither implementation here fetches anything.
ManualReviewProvider is always available because "manual import" already
*is* a real, working feature (POST /businesses/{id}/reviews,
app.routers.creative) — nothing to gate. GoogleReviewProvider exists only
to report honest availability — Section 4's rules are explicit that this
codebase must NEVER scrape Google Maps HTML, use an undocumented
endpoint, or invent an API response, so until a real, documented Google
Places/Business Profile API credential is wired in, GoogleReviewProvider
has nothing to fetch and must say so plainly rather than pretend."""

from abc import ABC, abstractmethod
from typing import ClassVar

from app.domain.enums import ReviewSource


class ReviewProvider(ABC):
    source: ClassVar[ReviewSource]

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def unavailable_reason(self) -> str | None:
        """None when is_available() is True."""


class ManualReviewProvider(ReviewProvider):
    source = ReviewSource.MANUAL

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None


class GoogleReviewProvider(ReviewProvider):
    source = ReviewSource.GOOGLE

    def __init__(self, *, api_key: str | None, place_id: str | None) -> None:
        self._api_key = api_key
        self._place_id = place_id

    def is_available(self) -> bool:
        return bool(self._api_key and self._place_id)

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return "Google Reviews is not configured on this server."
