import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_pusher_client():
    import pusher

    return pusher.Pusher(
        app_id=settings.PUSHER_APP_ID,
        key=settings.PUSHER_KEY,
        secret=settings.PUSHER_SECRET,
        cluster=settings.PUSHER_CLUSTER,
    )


def publish_notification_event(notification):
    """Trigger a ``new-notification`` event on the recipient's private channel.

    Must never raise — Pusher failures are logged and swallowed so the caller
    (API view or Celery task) can proceed normally.
    """
    from apps.notifications.serializers import NotificationSerializer

    try:
        client = _get_pusher_client()
        data = NotificationSerializer(notification).data
        client.trigger(
            f"private-user-{notification.recipient_id}",
            "new-notification",
            data,
        )
    except Exception:
        logger.exception(
            "Failed to push new-notification event for notification %s",
            notification.id,
        )


def publish_unread_count_update(user_id, count):
    """Trigger an ``unread-count-updated`` event on the user's private channel."""
    try:
        client = _get_pusher_client()
        client.trigger(
            f"private-user-{user_id}",
            "unread-count-updated",
            {"count": count},
        )
    except Exception:
        logger.exception(
            "Failed to push unread-count-updated event for user %s", user_id
        )


def publish_notification_read(notification):
    """Trigger a ``notification-read`` event on the recipient's private channel."""
    try:
        client = _get_pusher_client()
        client.trigger(
            f"private-user-{notification.recipient_id}",
            "notification-read",
            {"id": str(notification.id)},
        )
    except Exception:
        logger.exception(
            "Failed to push notification-read event for notification %s",
            notification.id,
        )
