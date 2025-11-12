#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.base import session_scope
from app.db.models import Clip, Video
from app.services.storage import remove_media_path


@dataclass
class OrphanReport:
    video_dirs: list[Path]
    clip_dirs: list[Path]


async def _fetch_existing_ids() -> tuple[set[int], set[int]]:
    async with session_scope() as session:
        video_rows = await session.execute(select(Video.id))
        clip_rows = await session.execute(select(Clip.id))
        return set(video_rows.scalars().all()), set(clip_rows.scalars().all())


def _scan_orphans(base: Path, existing_ids: set[int], subdir: str) -> list[Path]:
    target = base / subdir
    if not target.exists():
        return []
    orphans: list[Path] = []
    for entry in target.iterdir():
        if not entry.is_dir():
            continue
        try:
            dir_id = int(entry.name)
        except ValueError:
            continue
        if dir_id not in existing_ids:
            orphans.append(entry)
    return orphans


async def find_orphans(media_base: Path) -> OrphanReport:
    videos, clips = await _fetch_existing_ids()
    video_orphans = _scan_orphans(media_base, videos, "videos")
    clip_orphans = _scan_orphans(media_base, clips, "clips")
    return OrphanReport(video_dirs=video_orphans, clip_dirs=clip_orphans)


def delete_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        remove_media_path(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List or delete orphaned media directories (videos/clips).",
    )
    parser.add_argument(
        "--media-dir",
        default=settings.MEDIA_STORAGE_DIR,
        help="Base media directory (defaults to MEDIA_STORAGE_DIR).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the orphaned directories instead of just listing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    media_dir = Path(args.media_dir).resolve()
    print(f"Scanning media directory: {media_dir}")
    report: OrphanReport = asyncio.run(find_orphans(media_dir))
    print(f"Found {len(report.video_dirs)} orphan video directories")
    print(f"Found {len(report.clip_dirs)} orphan clip directories")

    if not args.delete:
        if report.video_dirs:
            print("\nVideo directories:")
            for path in report.video_dirs:
                print(f" - {path}")
        if report.clip_dirs:
            print("\nClip directories:")
            for path in report.clip_dirs:
                print(f" - {path}")
        print("\nRun again with --delete to remove them.")
        return

    delete_paths(report.video_dirs)
    delete_paths(report.clip_dirs)
    print("Cleanup complete.")


if __name__ == "__main__":
    main()
