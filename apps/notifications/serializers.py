from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Notification, NotificationType


class NotificationSerializer(serializers.ModelSerializer):
    notification_type = serializers.SlugField(
        source="notification_type.key", read_only=True
    )

    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient",
            "notification_type",
            "actor",
            "message",
            "verb",
            "data",
            "priority",
            "is_read",
            "read_at",
            "idempotency_key",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "recipient",
            "actor",
            "is_read",
            "read_at",
            "created_at",
        ]


class NotificationCreateSerializer(serializers.Serializer):
    recipient_id = serializers.IntegerField()
    notification_type_key = serializers.SlugField()
    actor_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    message = serializers.CharField()
    verb = serializers.CharField(required=False, allow_blank=True, default="")
    data = serializers.JSONField(required=False, default=dict)
    priority = serializers.ChoiceField(
        choices=Notification.Priority.values,
        default=Notification.Priority.NORMAL,
    )
    idempotency_key = serializers.CharField(
        required=False, allow_null=True, default=None, max_length=255
    )

    def validate_recipient_id(self, value):
        User = get_user_model()
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Recipient user does not exist.")
        return value

    def validate_actor_id(self, value):
        if value is not None:
            User = get_user_model()
            if not User.objects.filter(id=value).exists():
                raise serializers.ValidationError("Actor user does not exist.")
        return value


class BulkNotificationCreateSerializer(serializers.Serializer):
    notifications = NotificationCreateSerializer(many=True, min_length=1)
