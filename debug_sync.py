import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.base import get_sessionmaker
from app.db.models import (
    AuthProvider,
    ClipGenerationMode,
    User,
    Video,
    VideoIngestType,
    VideoStatus,
)


async def main() -> None:
    try:
        session_maker = get_sessionmaker()
        async with session_maker() as session:
            print("Connected to DB")

            # Create User
            email = "test@example.com"
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                print(f"Creating user {email}...")
                user = User(
                    email=email,
                    full_name="Test User",
                    password_hash=hash_password("password"),
                    primary_auth_provider=AuthProvider.EMAIL.value,
                    is_active=True,
                )
                session.add(user)
                await session.commit()
                print(f"User created with ID: {user.id}")
            else:
                print(f"User {email} already exists with ID: {user.id}")

            # Test Data - Scenario 3: Large File Size
            import time

            source_url = f"https://www.youtube.com/watch?v=overflow_{int(time.time())}"
            local_path = "/Users/joaquinastelarra/Documents/TV7/flutter-tv7/forgotten_client/assets/videos/large_video.mp4"
            original_filename = "large_video.mp4"

            # Check if exists
            stmt = select(Video).where(Video.source_url == source_url)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                print(f"Video already exists with ID: {existing.id}")
                print("Attempting to insert duplicate to check for constraints...")
            else:
                print("Video does not exist. Attempting to create...")

            video = Video(
                source_url=source_url,
                local_path=local_path,
                ingest_type=VideoIngestType.UPLOAD.value,
                original_filename=original_filename,
                upload_checksum=None,
                upload_file_size_bytes=1000,
                transcript_text=None,
                transcript_language=None,
                duration_seconds=120,
                file_size_bytes=3 * 1024 * 1024 * 1024,  # 3GB
                workspace_root=None,
                status=VideoStatus.READY.value,
                clip_generation_mode=ClipGenerationMode.REPLACE.value,
                requested_by_user_id=user.id,
            )

            try:
                session.add(video)
                await session.commit()
                print(f"Successfully created video with ID: {video.id}")
            except Exception as e:  # noqa: BLE001
                print(f"Caught Exception: {type(e).__name__}: {e}")
                import traceback

                traceback.print_exc()
    except Exception as e:  # noqa: BLE001
        print(f"Setup Exception: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
