from celery import shared_task
from django.utils import timezone


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def dispatch_notification(self, notification_id):
    from .models import DeliveryLog, Notification, NotificationPreference
    from .services.pusher_client import publish_notification_event

    notification = Notification.objects.select_related(
        "notification_type", "recipient"
    ).get(id=notification_id)

    pref = NotificationPreference.objects.filter(
        user=notification.recipient,
        notification_type=notification.notification_type,
    ).first()

    in_app = pref.in_app if pref else True
    email = pref.email if pref else False

    if in_app:
        dl_error = None
        try:
            publish_notification_event(notification)
            dl_status = DeliveryLog.Status.SENT
        except Exception as e:
            dl_status = DeliveryLog.Status.FAILED
            dl_error = str(e)

        dl, created = DeliveryLog.objects.get_or_create(
            notification=notification,
            channel=DeliveryLog.Channel.IN_APP,
            defaults={
                "status": dl_status,
                "attempts": 1,
                "last_error": dl_error,
                "sent_at": timezone.now() if dl_status == DeliveryLog.Status.SENT else None,
            },
        )
        if not created:
            dl.attempts += 1
            dl.status = dl_status
            dl.last_error = dl_error
            dl.sent_at = (
                timezone.now()
                if dl_status == DeliveryLog.Status.SENT
                else None
            )
            dl.save(update_fields=["status", "attempts", "last_error", "sent_at"])

    if email:
        send_email_notification.delay(notification_id)


@shared_task(bind=True, ignore_result=True)
def send_email_notification(self, notification_id):
    pass


@shared_task(bind=True, ignore_result=True)
def send_digest_emails(self):
    pass


@shared_task(bind=True, ignore_result=True)
def cleanup_old_notifications(self):
    pass
