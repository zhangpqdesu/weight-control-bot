from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_settings
from .models import PersonKey
from .service import DietTrackerService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diet tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a food entry")
    add.add_argument("--user", choices=["me", "gf"], required=True)
    add.add_argument("--text")
    add.add_argument("--image", type=Path)

    today = sub.add_parser("today", help="Show today's summary")
    today.add_argument("--user", choices=["me", "gf"], required=True)

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args()
    settings = load_settings()
    service = DietTrackerService(settings)

    if args.command == "add":
        entry = service.add_food(
            person_key=args.user,
            text=args.text,
            image_path=args.image,
        )
        print(service.entry_reply(entry))
        return

    if args.command == "today":
        print(service.today_reply(args.user))
        return


if __name__ == "__main__":
    main()
