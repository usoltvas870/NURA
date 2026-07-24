import argparse
import asyncio
import sys

from sqlalchemy.exc import IntegrityError

from core.config import settings
from core.database import get_async_sessionmaker
from core.services.attribution import AttributionService, AttributionValidationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a Telegram attribution link")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    for argument in ("platform", "source", "campaign", "content-id", "topic"):
        create.add_argument(f"--{argument}", required=True)
    create.add_argument("--label")
    create.add_argument("--code")
    create.add_argument(
        "--allow-production",
        action="store_true",
        help="Explicitly allow creation against a production-configured database",
    )
    return parser


async def _create(args: argparse.Namespace) -> int:
    link = await AttributionService(get_async_sessionmaker()).create_link(
        code=args.code, platform=args.platform, source=args.source,
        campaign=args.campaign, content_id=args.content_id, topic=args.topic,
        label=args.label,
    )
    print(f"code: {link.code}")
    print(f"start_parameter: a_{link.code}")
    if settings.bot_username:
        print(f"telegram_deep_link: https://t.me/{settings.bot_username}?start=a_{link.code}")
    print(f"metadata: {link.platform} | {link.source} | {link.campaign} | {link.content_id} | {link.topic}")
    return 0


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    if settings.is_production and not args.allow_production:
        print(
            "error: production environment requires --allow-production",
            file=sys.stderr,
        )
        return 2
    try:
        return asyncio.run(_create(args))
    except (AttributionValidationError, IntegrityError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("error: attribution link could not be created", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
