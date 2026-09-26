"""``manage.py tenant_api_key_rotate`` -- rotate a key by its public prefix."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_tenant_apikeys.models import get_api_key_model


class Command(BaseCommand):
    help = (
        "Rotate an API key: issue a replacement with the same tenant, scopes, "
        "and expiration, and revoke the old one (or, with --grace-days, let the "
        "old one keep working for that many days). Prints the new raw key once "
        "-- it cannot be recovered afterwards. Resolves the concrete model via "
        "TENANT_API_KEY_MODEL."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("prefix", help="The current key's prefix, e.g. tak_live_3f9a2c1d.")
        parser.add_argument(
            "--grace-days",
            type=int,
            default=None,
            metavar="DAYS",
            help=(
                "Don't revoke the old key immediately; let it expire this many days "
                "from now so clients can switch over. Omit for a compromised key."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        model = get_api_key_model()
        try:
            old_key = model.objects.get(prefix=options["prefix"])
        except model.DoesNotExist as exc:
            raise CommandError(f"No API key found with prefix {options['prefix']!r}.") from exc

        try:
            grace_days = options["grace_days"]
            grace_period = timedelta(days=grace_days) if grace_days is not None else None
            new_key, raw_key = old_key.rotate(grace_period=grace_period)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Rotated {old_key.prefix!r} ({old_key.name})."))
        if grace_period is not None:
            self.stdout.write(
                f"The old key stays valid until {old_key.expires_at:%Y-%m-%d %H:%M %Z}."
            )
        self.stdout.write(f"New prefix: {new_key.prefix}")
        self.stdout.write(
            self.style.WARNING(f"New raw key (copy it now, it will not be shown again):\n{raw_key}")
        )
