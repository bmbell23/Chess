"""Docker entrypoint: run migrations, then serve."""
import subprocess
import sys

import uvicorn

from chess_stats.config import get_settings


def main() -> None:
    settings = get_settings()

    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"])
    if result.returncode != 0:
        print("alembic upgrade failed — refusing to start", file=sys.stderr)
        sys.exit(result.returncode)

    uvicorn.run("chess_stats.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
