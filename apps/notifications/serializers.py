from django.contrib.auth import get_user_model
from django.utils.text import slugify
from rest_framework import serializers

from .models import (
    Notification,
    NotificationPreference,
    NotificationType,
    Room,
    RoomMember,
)


class NotificationSerializer(serializers.ModelSerializer):
    notification_type = serializers.SlugField(
        source="notification_type.key", read_only=True
    )
    room = serializers.SlugField(source="room.slug", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient",
            "notification_type",
            "actor",
            "room",
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
            "room",
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

    def validate_notification_type_key(self, value):
        if not NotificationType.objects.filter(key=value).exists():
            raise serializers.ValidationError(
                f"NotificationType '{value}' does not exist."
            )
        return value

    def validate_actor_id(self, value):
        if value is not None:
            User = get_user_model()
            if not User.objects.filter(id=value).exists():
                raise serializers.ValidationError("Actor user does not exist.")
        return value


class BulkNotificationCreateSerializer(serializers.Serializer):
    notifications = NotificationCreateSerializer(many=True, min_length=1)


class NotificationPreferenceReadSerializer(serializers.ModelSerializer):
    notification_type = serializers.SlugField(
        source="notification_type.key", read_only=True
    )

    class Meta:
        model = NotificationPreference
        fields = ["notification_type", "in_app", "email"]


class NotificationPreferenceWriteItemSerializer(serializers.Serializer):
    notification_type_key = serializers.SlugField()
    in_app = serializers.BooleanField(required=False)
    email = serializers.BooleanField(required=False)

    def validate_notification_type_key(self, value):
        if not NotificationType.objects.filter(key=value).exists():
            raise serializers.ValidationError(
                f"NotificationType '{value}' does not exist."
            )
        return value


class RoomSerializer(serializers.ModelSerializer):
    created_by = serializers.IntegerField(source="created_by_id", read_only=True)
    member_count = serializers.IntegerField(read_only=True, default=0)
    is_member = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Room
        fields = [
            "slug",
            "name",
            "description",
            "created_by",
            "member_count",
            "is_member",
            "created_at",
        ]


class RoomCreateSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)

    class Meta:
        model = Room
        fields = ["slug", "name", "description"]

    def create(self, validated_data):
        base_slug = validated_data.get("slug") or slugify(
            validated_data["name"]
        ) or "room"
        slug = base_slug
        counter = 2
        while Room.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return Room.objects.create(
            slug=slug,
            name=validated_data["name"],
            description=validated_data.get("description", ""),
        )


class RoomMemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = RoomMember
        fields = ["user_id", "email", "joined_at"]
