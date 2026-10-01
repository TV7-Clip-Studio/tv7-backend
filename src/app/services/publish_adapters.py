from __future__ import annotations

from app.core.config import settings
from app.db.base import get_sessionmaker
from app.services.publish_execution import PublishAdapter
from app.services.youtube_oauth import YouTubeOAuthError, oauth_configured, token_cipher
from app.services.youtube_publish import YouTubePublishAdapter


def youtube_publishing_ready() -> bool:
    if not (
        settings.YOUTUBE_PUBLISH_ENABLED
        and settings.YOUTUBE_API_AUDIT_APPROVED
        and oauth_configured()
    ):
        return False
    try:
        token_cipher()
    except YouTubeOAuthError:
        return False
    return True


def configured_adapters() -> dict[str, PublishAdapter]:
    """Return only configured real adapters whose release gates are enabled."""

    if youtube_publishing_ready():
        return {"youtube_shorts": YouTubePublishAdapter(get_sessionmaker())}
    return {}
