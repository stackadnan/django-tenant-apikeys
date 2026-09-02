"""``manage.py tenant_api_key_revoke`` -- revoke a key by its public prefix."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from django_tenant_apikeys.models import get_api_key_model


class Command(BaseCommand):
    help = (
        "Revoke an API key immediately, given its prefix (the part before the "
        "dot -- never the raw secret, which isn't stored). Resolves the "
        "concrete model via TENANT_API_KEY_MODEL."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("prefix", help="The key's prefix, e.g. tak_live_3f9a2c1d.")
        parser.add_argument(
            "--reason", default="", help="Optional note stored in the key's revoked_reason."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        model = get_api_key_model()
        try:
            api_key = model.objects.get(prefix=options["prefix"])
        except model.DoesNotExist as exc:
            raise CommandError(f"No API key found with prefix {options['prefix']!r}.") from exc

        api_key.revoke(reason=options["reason"])
        self.stdout.write(
            self.style.SUCCESS(f"Revoked API key {api_key.prefix!r} ({api_key.name}).")
        )
