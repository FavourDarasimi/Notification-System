import django_filters

from .models import Notification


class NotificationFilter(django_filters.FilterSet):
    is_read = django_filters.BooleanFilter()
    notification_type = django_filters.CharFilter(
        field_name="notification_type__key"
    )
    room = django_filters.CharFilter(field_name="room__slug")

    class Meta:
        model = Notification
        fields = ["is_read", "notification_type", "room"]
