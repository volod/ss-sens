"""ss-sens CLI: ``ss-sens serve`` / ``python -m ss_sens serve``."""

import argparse
import sys

from .config import settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ss-sens", description="ss-sens sensor mesh service")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the FastAPI sensor mesh service")
    serve.add_argument("--host", default=settings.http_host, help="Bind host")
    serve.add_argument("--port", type=int, default=settings.http_port, help="Bind port")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .app import app

        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
