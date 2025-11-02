from __future__ import annotations

import sys

from dramatiq.cli import main as dramatiq_main

from app.services import tasks  # noqa: F401 - ensure actors register
from app.services.queue import ensure_broker


def main() -> None:
    ensure_broker()
    sys.argv = ["dramatiq", "app.services.tasks"]
    dramatiq_main()


if __name__ == "__main__":
    main()
