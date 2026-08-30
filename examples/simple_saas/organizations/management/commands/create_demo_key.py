from django.core.management.base import BaseCommand

from organizations.models import Organization, OrganizationAPIKey


class Command(BaseCommand):
    help = "Create a demo Organization and issue it an API key, printing the raw key once."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="Acme Inc.", help="Organization name to create.")

    def handle(self, *args, **options):
        org, created = Organization.objects.get_or_create(name=options["org"])
        instance, raw_key = OrganizationAPIKey.generate_key(
            name="demo key",
            tenant=org,
            scopes=["whoami:read"],
        )

        status = "created" if created else "existing"
        self.stdout.write(self.style.SUCCESS(f"Organization: {org.name} ({status})"))
        self.stdout.write(f"API key prefix: {instance.prefix}")
        self.stdout.write(
            self.style.WARNING(f"Raw key (copy this now, it will not be shown again):\n{raw_key}")
        )
        self.stdout.write("\nTry it:")
        self.stdout.write(
            f'  curl -H "Authorization: Api-Key {raw_key}" http://127.0.0.1:8000/api/whoami/'
        )
