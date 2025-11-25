import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import text

from app.db.base import get_sessionmaker


async def main() -> None:
    try:
        session_maker = get_sessionmaker()
        async with session_maker() as session:
            print("Connected to DB")

            result = await session.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'videos';"
                )
            )

            for row in result:
                print(f"{row[0]}: {row[1]}")

    except Exception as e:
        print(f"Exception: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
