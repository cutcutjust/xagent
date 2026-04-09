"""Protocol definitions — every platform implements these."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.content import CollectedContent, PlatformDraft, UniversalDraft


@runtime_checkable
class PlatformResearcher(Protocol):
    async def discover(self, topics: list[str]) -> list[str]:
        """Return a list of URLs to investigate."""
        ...

    async def collect(self, url: str) -> CollectedContent | None:
        """Open url, extract content, return CollectedContent or None if irrelevant."""
        ...


@runtime_checkable
class PlatformComposer(Protocol):
    async def compose(
        self, draft: UniversalDraft, post_type: str = "short_post"
    ) -> PlatformDraft:
        """Format a UniversalDraft into a platform-specific PlatformDraft."""
        ...


@runtime_checkable
class PlatformPublisher(Protocol):
    async def publish(self, draft: PlatformDraft) -> str:
        """Publish the draft. Returns the URL of the published post."""
        ...
