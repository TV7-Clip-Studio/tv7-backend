from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class ClipRepository:
    """Placeholder repository for clip persistence; expand as clip endpoints arrive."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
