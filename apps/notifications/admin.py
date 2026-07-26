from django.contrib import admin, messages

from .models import (
    DeliveryLog,
    Notification,
    NotificationPreference,
    NotificationTemplate,
    NotificationType,
)


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
        "priority",
        "is_read",
        "created_at",
    )
    list_filter = ("is_read", "priority", "notification_type", "created_at")
    search_fields = ("recipient__email", "message", "verb")
    raw_id_fields = ("recipient", "actor", "notification_type")
    readonly_fields = ("created_at",)
    list_select_related = ("recipient", "actor", "notification_type")


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


def requeue_failed_deliveries(modeladmin, request, queryset):
    """Requeue selected failed or retrying deliveries.

    Stub implementation — actual Celery task wired in Phase 4.
    """
    failed = queryset.filter(
        status__in=[DeliveryLog.Status.FAILED, DeliveryLog.Status.RETRYING],
    )
    count = failed.count()
    if count == 0:
        modeladmin.message_user(request, "No failed/retrying deliveries selected.", messages.WARNING)
        return

    # TODO: Phase 4 — call requeue_failed_delivery.delay(delivery_log_id)
    # for log in failed:
    #     requeue_failed_delivery.delay(log.id)
    failed.update(status=DeliveryLog.Status.PENDING, last_error=None)
    modeladmin.message_user(
        request,
        f"Queued {count} delivery log(s) for retry (stub — Celery task not yet wired).",
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
