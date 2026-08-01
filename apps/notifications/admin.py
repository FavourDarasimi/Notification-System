from django.contrib import admin, messages

from .models import (
    DeliveryLog,
    Notification,
    NotificationPreference,
    NotificationTemplate,
    NotificationType,
    Room,
    RoomMember,
)
from .tasks import dispatch_notification, send_email_notification


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "description", "default_channels")
    search_fields = ("key", "name")
    prepopulated_fields = {}


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient",
        "notification_type",
        "room",
        "priority",
        "is_read",
        "created_at",
    )
    list_filter = ("is_read", "priority", "notification_type", "room", "created_at")
    search_fields = ("recipient__email", "message", "verb")
    raw_id_fields = ("recipient", "actor", "notification_type")
    readonly_fields = ("created_at",)
    list_select_related = ("recipient", "actor", "notification_type", "room")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "in_app", "email")
    list_filter = ("in_app", "email", "notification_type")
    search_fields = ("user__email",)
    raw_id_fields = ("user", "notification_type")


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("notification_type", "channel", "subject_template")
    list_filter = ("channel", "notification_type")
    raw_id_fields = ("notification_type",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_by", "created_at")
    search_fields = ("name", "slug")
    list_select_related = ("created_by",)


@admin.register(RoomMember)
class RoomMemberAdmin(admin.ModelAdmin):
    list_display = ("room", "user", "joined_at")
    search_fields = ("room__name", "user__email")
    raw_id_fields = ("room", "user")
    list_select_related = ("room", "user")


def requeue_failed_deliveries(modeladmin, request, queryset):
    """Requeue selected failed or retrying deliveries."""
    failed = queryset.filter(
        status__in=[DeliveryLog.Status.FAILED, DeliveryLog.Status.RETRYING],
    )
    count = failed.count()
    if count == 0:
        modeladmin.message_user(request, "No failed/retrying deliveries selected.", messages.WARNING)
        return

    for log in failed.select_related("notification"):
        log.status = DeliveryLog.Status.RETRYING
        log.last_error = None
        log.save(update_fields=["status", "last_error"])

        if log.channel == DeliveryLog.Channel.IN_APP:
            dispatch_notification.delay(log.notification_id)
        elif log.channel == DeliveryLog.Channel.EMAIL:
            send_email_notification.delay(log.notification_id)

    modeladmin.message_user(
        request,
        f"Requeued {count} delivery log(s) for retry.",
        messages.SUCCESS,
    )


requeue_failed_deliveries.short_description = "Requeue selected failed deliveries"


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "notification",
        "channel",
        "status",
        "attempts",
        "sent_at",
    )
    list_filter = ("status", "channel", "sent_at")
    search_fields = ("notification__recipient__email", "last_error")
    raw_id_fields = ("notification",)
    readonly_fields = ("sent_at",)
    list_select_related = ("notification",)
    actions = [requeue_failed_deliveries]
