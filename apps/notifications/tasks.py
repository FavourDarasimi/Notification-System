import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template import Template, Context
from django.utils import timezone

logger = logging.getLogger(__name__)


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


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def send_email_notification(self, notification_id):
    from .models import DeliveryLog, Notification, NotificationTemplate

    notification = Notification.objects.select_related(
        "notification_type", "recipient"
    ).get(id=notification_id)

    template = NotificationTemplate.objects.filter(
        notification_type=notification.notification_type,
        channel=NotificationTemplate.Channel.EMAIL,
    ).first()

    context = {
        "message": notification.message,
        "verb": notification.verb,
        "data": notification.data,
        "priority": notification.priority,
        "created_at": notification.created_at,
        "notification_id": str(notification.id),
        "type_name": notification.notification_type.name,
        "type_key": notification.notification_type.key,
        "recipient_email": notification.recipient.email,
    }

    try:
        if template:
            subject = Template(template.subject_template).render(Context(context))
            body = Template(template.body_template).render(Context(context))
        else:
            subject = notification.notification_type.name
            body = notification.message

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient.email],
            fail_silently=False,
        )
        dl_status = DeliveryLog.Status.SENT
        dl_error = None
    except Exception as e:
        dl_status = DeliveryLog.Status.FAILED
        dl_error = str(e)
        raise

    dl, created = DeliveryLog.objects.get_or_create(
        notification=notification,
        channel=DeliveryLog.Channel.EMAIL,
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


@shared_task(bind=True, ignore_result=True)
def send_digest_emails(self):
    from django.contrib.auth import get_user_model

    from .models import Notification, NotificationPreference

    User = get_user_model()

    user_ids = list(
        NotificationPreference.objects.filter(email=True)
        .values_list("user_id", flat=True)
        .distinct()
    )

    if not user_ids:
        return

    users = User.objects.filter(id__in=user_ids).only("id", "email")

    for user in users:
        unread = list(
            Notification.objects.filter(recipient=user, is_read=False)
            .select_related("notification_type")
            .only("message", "notification_type__name", "created_at")
            .order_by("-created_at")
        )
        if not unread:
            continue

        count = len(unread)
        lines = [
            f"- [{n.notification_type.name}] {n.message}"
            for n in unread
        ]
        body = (
            f"Hi {user.email},\n\n"
            f"You have {count} unread notification{'s' if count != 1 else ''}:\n\n"
            + "\n".join(lines)
            + "\n\nVisit the app to view them in detail."
        )

        send_mail(
            subject=f"Daily Digest — {count} unread notification{'s' if count != 1 else ''}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )


@shared_task(bind=True, ignore_result=True)
def cleanup_old_notifications(self):
    from datetime import timedelta

    from .models import Notification

    retention_days = getattr(settings, "NOTIFICATION_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=retention_days)

    deleted_count, _ = Notification.objects.filter(
        created_at__lt=cutoff
    ).delete()

    logger.info(
        "Cleaned up %d notifications older than %d days",
        deleted_count,
        retention_days,
    )
