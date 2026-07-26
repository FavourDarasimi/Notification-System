from django.core.management.base import BaseCommand

from apps.notifications.models import NotificationType

SEED_DATA = [
    {
        "key": "comment_reply",
        "name": "Comment Reply",
        "description": "Someone replied to your comment.",
        "default_channels": ["in_app", "email"],
    },
    {
        "key": "invoice_paid",
        "name": "Invoice Paid",
        "description": "An invoice has been paid successfully.",
        "default_channels": ["in_app", "email"],
    },
    {
        "key": "friend_request",
        "name": "Friend Request",
        "description": "You received a new friend request.",
        "default_channels": ["in_app", "email"],
    },
    {
        "key": "welcome",
        "name": "Welcome Message",
        "description": "Welcome to the platform.",
        "default_channels": ["in_app"],
    },
    {
        "key": "system_alert",
        "name": "System Alert",
        "description": "Important system-wide announcement.",
        "default_channels": ["in_app", "email"],
    },
]


class Command(BaseCommand):
    help = "Seed example NotificationType rows for local development."

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for item in SEED_DATA:
            _, is_new = NotificationType.objects.get_or_create(
                key=item["key"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "default_channels": item["default_channels"],
                },
            )
            if is_new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created}, skipped {skipped} existing."
            )
        )
