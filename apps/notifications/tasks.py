from celery import shared_task


@shared_task(bind=True, ignore_result=True)
def dispatch_notification(self, notification_id):
    pass


@shared_task(bind=True, ignore_result=True)
def send_email_notification(self, notification_id):
    pass


@shared_task(bind=True, ignore_result=True)
def send_digest_emails(self):
    pass


@shared_task(bind=True, ignore_result=True)
def cleanup_old_notifications(self):
    pass
