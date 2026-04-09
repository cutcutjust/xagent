"""Custom exceptions for SightOps."""


class SightOpsError(Exception):
    """Base exception."""


class BrowserError(SightOpsError):
    """Browser / Playwright error."""


class VisionError(SightOpsError):
    """LLM vision or action planning error."""


class ActionFailed(SightOpsError):
    """An action was executed but produced an unexpected result."""


class ExtractionError(SightOpsError):
    """Failed to extract content from a page."""


class PublishError(SightOpsError):
    """Publishing failed or was rejected."""


class NotionError(SightOpsError):
    """Notion API error."""


class HumanReviewRequired(SightOpsError):
    """Workflow paused — human must review before continuing."""
