import uuid

from django.conf import settings
from django.db import models


class NotificationType(models.Model):
    key = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    default_channels = models.JSONField(
        default=list,
        help_text='List of channel keys, e.g. ["in_app", "email"]',
    )

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.name


class Notification(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acted_notifications",
    )
    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    message = models.TextField()
    verb = models.CharField(max_length=255, blank=True, default="")
    data = models.JSONField(default=dict)
    room = models.ForeignKey(
        "Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "-created_at"],
                name="idx_notif_recipient_created",
            ),
            models.Index(
                fields=["recipient", "is_read"],
                name="idx_notif_recipient_read",
            ),
            models.Index(
                fields=["recipient", "room", "-created_at"],
                name="idx_notif_recipient_room",
            ),
        ]

    def __str__(self):
        return f"{self.recipient} - {self.notification_type.key} - {self.created_at}"


class NotificationPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=False)

    class Meta:
        ordering = ["user", "notification_type"]
        unique_together = [("user", "notification_type")]

    def __str__(self):
        return f"{self.user} / {self.notification_type.key}"


class NotificationTemplate(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-App"
        EMAIL = "email", "Email"

    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.CASCADE,
        related_name="templates",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    subject_template = models.TextField(
        help_text="Subject line template (used for email channel).",
    )
    body_template = models.TextField(
        help_text="Body template. Use Django template syntax or simple placeholders.",
    )

    class Meta:
        ordering = ["notification_type", "channel"]
        unique_together = [("notification_type", "channel")]

    def __str__(self):
        return f"{self.notification_type.key} / {self.channel}"


class DeliveryLog(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-App"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="delivery_logs",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.notification} / {self.channel} / {self.status}"


class Room(models.Model):
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_rooms",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoomMember(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="room_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at"]
        unique_together = [("room", "user")]

    def __str__(self):
        return f"{self.user} / {self.room}"
