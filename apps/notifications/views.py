from django.conf import settings
from django.db import transaction
from django.db import connections
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import pusher

from .auth import ServiceTokenAuthentication
from .filters import NotificationFilter
from .models import (
    Notification,
    NotificationPreference,
    NotificationType,
    Room,
    RoomMember,
)
from .pagination import NotificationCursorPagination
from .serializers import (
    BulkNotificationCreateSerializer,
    NotificationCreateSerializer,
    NotificationPreferenceReadSerializer,
    NotificationPreferenceWriteItemSerializer,
    NotificationSerializer,
    RoomCreateSerializer,
    RoomMemberSerializer,
    RoomSerializer,
)
from .tasks import dispatch_notification
from .throttling import NotificationsListThrottle, NotificationsTestThrottle


def create_notifications(items):
    """Shared notification create path (idempotency, bulk create, dispatch)."""
    seen_keys = {}
    to_create = []
    results = []

    for item in items:
        key = item.get("idempotency_key")
        if key:
            if key in seen_keys:
                n = seen_keys[key]
                n._existing = True
                results.append(n)
                continue
            try:
                existing = Notification.objects.get(idempotency_key=key)
                existing._existing = True
                seen_keys[key] = existing
                results.append(existing)
                continue
            except Notification.DoesNotExist:
                pass

        notification = Notification(
            recipient_id=item["recipient_id"],
            notification_type_id=NotificationType.objects.values_list(
                "id", flat=True
            ).get(key=item["notification_type_key"]),
            actor_id=item.get("actor_id"),
            message=item["message"],
            verb=item.get("verb", ""),
            data=item.get("data", {}),
            priority=item.get("priority", Notification.Priority.NORMAL),
            idempotency_key=item.get("idempotency_key"),
        )
        to_create.append(notification)
        if key:
            seen_keys[key] = notification

    if to_create:
        with transaction.atomic():
            created = Notification.objects.bulk_create(to_create)
            results.extend(created)
            for notification in created:
                transaction.on_commit(
                    lambda n=notification: dispatch_notification.delay(n.id)
                )

    return results


class NotificationListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    filterset_class = NotificationFilter

    def get_authenticators(self):
        if self.request.method == "POST":
            return [ServiceTokenAuthentication()]
        from rest_framework_simplejwt.authentication import JWTAuthentication

        return [JWTAuthentication()]

    def get_throttles(self):
        if self.request.method == "GET":
            return [NotificationsListThrottle()]
        return super().get_throttles()

    def get(self, request):
        queryset = Notification.objects.filter(recipient=request.user)
        filter_backend = DjangoFilterBackend()
        queryset = filter_backend.filter_queryset(request, queryset, self)
        paginator = NotificationCursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        is_bulk = "notifications" in request.data and isinstance(
            request.data["notifications"], list
        )
        if is_bulk:
            serializer = BulkNotificationCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            items = serializer.validated_data["notifications"]
        else:
            serializer = NotificationCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            items = [serializer.validated_data]

        results = create_notifications(items)
        any_new = any(
            not hasattr(n, "_existing") for n in results
        )

        if is_bulk:
            serializer = NotificationSerializer(results, many=True)
        else:
            serializer = NotificationSerializer(results[0])

        status_code = status.HTTP_201_CREATED if any_new else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)


class NotificationTestCreateView(APIView):
    """Feature-flagged test endpoint: self-notification via the real create path."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [NotificationsTestThrottle]

    def post(self, request):
        if not getattr(settings, "DJANGO_ENABLE_TEST_ENDPOINTS", False):
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = NotificationCreateSerializer(
            data={
                "recipient_id": request.user.id,
                "notification_type_key": request.data.get(
                    "notification_type_key"
                ),
                "message": request.data.get("message", ""),
            }
        )
        serializer.is_valid(raise_exception=True)

        results = create_notifications([serializer.validated_data])
        serializer = NotificationSerializer(results[0])
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class NotificationUnreadCountView(APIView):
    throttle_classes = [NotificationsListThrottle]

    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        return Response({"count": count})


class NotificationMarkAllReadView(APIView):
    def post(self, request):
        now = timezone.now()
        updated = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True, read_at=now)
        return Response({"updated": updated})


class NotificationReadView(APIView):
    def patch(self, request, id):
        notification = get_object_or_404(
            Notification, id=id, recipient=request.user
        )
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
        serializer = NotificationSerializer(notification)
        return Response(serializer.data)


class NotificationDeleteView(APIView):
    def delete(self, request, id):
        notification = get_object_or_404(
            Notification, id=id, recipient=request.user
        )
        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationPreferenceView(APIView):
    def get(self, request):
        preferences = self._get_or_create_preferences(request.user)
        serializer = NotificationPreferenceReadSerializer(preferences, many=True)
        return Response(serializer.data)

    def put(self, request):
        serializer = NotificationPreferenceWriteItemSerializer(
            data=request.data, many=True
        )
        serializer.is_valid(raise_exception=True)

        for item in serializer.validated_data:
            ntype = NotificationType.objects.get(
                key=item["notification_type_key"]
            )
            channels = ntype.default_channels or []
            pref, _ = NotificationPreference.objects.get_or_create(
                user=request.user,
                notification_type=ntype,
                defaults={
                    "in_app": "in_app" in channels,
                    "email": "email" in channels,
                },
            )

            changed = False
            if "in_app" in item and item["in_app"] != pref.in_app:
                pref.in_app = item["in_app"]
                changed = True
            if "email" in item and item["email"] != pref.email:
                pref.email = item["email"]
                changed = True
            if changed:
                pref.save()

        preferences = self._get_or_create_preferences(request.user)
        response_serializer = NotificationPreferenceReadSerializer(
            preferences, many=True
        )
        return Response(response_serializer.data)

    @staticmethod
    def _get_or_create_preferences(user):
        existing = {
            p.notification_type_id: p
            for p in NotificationPreference.objects.filter(
                user=user
            ).select_related("notification_type")
        }
        all_types = NotificationType.objects.all()
        result = []
        for ntype in all_types:
            if ntype.id in existing:
                result.append(existing[ntype.id])
            else:
                channels = ntype.default_channels or []
                pref = NotificationPreference.objects.create(
                    user=user,
                    notification_type=ntype,
                    in_app="in_app" in channels,
                    email="email" in channels,
                )
                result.append(pref)
        return result


class PusherAuthView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel_name = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")

        if not channel_name or not socket_id:
            return Response(
                {"error": "channel_name and socket_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expected = f"private-user-{request.user.id}"
        if channel_name != expected:
            return Response(
                {"error": "Forbidden channel"},
                status=status.HTTP_403_FORBIDDEN,
            )

        p = pusher.Pusher(
            app_id=settings.PUSHER_APP_ID,
            key=settings.PUSHER_KEY,
            secret=settings.PUSHER_SECRET,
            cluster=settings.PUSHER_CLUSTER,
        )

        auth = p.authenticate(
            channel=channel_name,
            socket_id=socket_id,
        )

        return Response(auth)


def _annotated_rooms(user):
    """Annotate member_count + is_member for a room queryset."""
    joined = RoomMember.objects.filter(room=OuterRef("pk"), user=user)
    return Room.objects.annotate(
        member_count=Count("memberships"),
        is_member=Exists(joined),
    )


class RoomListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rooms = _annotated_rooms(request.user).order_by("name")
        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save(created_by=request.user)
        RoomMember.objects.create(room=room, user=request.user)
        room = _annotated_rooms(request.user).get(pk=room.pk)
        return Response(
            RoomSerializer(room).data, status=status.HTTP_201_CREATED
        )


class RoomDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        room = (
            _annotated_rooms(request.user).filter(slug=slug).first()
        )
        if not room:
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )
        members = RoomMember.objects.filter(room=room).select_related("user")
        return Response(
            {
                "room": RoomSerializer(room).data,
                "members": RoomMemberSerializer(members, many=True).data,
            }
        )


class RoomJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        room = get_object_or_404(Room, slug=slug)
        RoomMember.objects.get_or_create(room=room, user=request.user)
        return Response({"joined": True})


class RoomLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        room = get_object_or_404(Room, slug=slug)
        RoomMember.objects.filter(room=room, user=request.user).delete()
        return Response({"left": True})


class RoomSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        room = get_object_or_404(Room, slug=slug)
        if not RoomMember.objects.filter(
            room=room, user=request.user
        ).exists():
            return Response(
                {"error": "Join the room before sending to it."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NotificationCreateSerializer(
            data={**request.data, "recipient_id": request.user.id}
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.validated_data
        item["room_id"] = room.id
        item["actor_id"] = request.user.id

        member_ids = list(
            RoomMember.objects.filter(room=room)
            .exclude(user=request.user)
            .values_list("user_id", flat=True)
        )

        if not member_ids:
            return Response({"count": 0, "notifications": []})

        ntype_id = NotificationType.objects.values_list("id", flat=True).get(
            key=item["notification_type_key"]
        )
        key = item.get("idempotency_key")
        to_create = [
            Notification(
                recipient_id=recipient_id,
                notification_type_id=ntype_id,
                actor_id=item["actor_id"],
                room_id=room.id,
                message=item["message"],
                verb=item.get("verb", ""),
                data=item.get("data", {}),
                priority=item.get("priority", Notification.Priority.NORMAL),
                idempotency_key=f"{key}:{recipient_id}" if key else None,
            )
            for recipient_id in member_ids
        ]

        created = []
        with transaction.atomic():
            if key:
                existing_keys = set(
                    Notification.objects.filter(
                        idempotency_key__in=[
                            n.idempotency_key for n in to_create
                        ]
                    ).values_list("idempotency_key", flat=True)
                )
                to_create = [
                    n for n in to_create if n.idempotency_key not in existing_keys
                ]
            created = Notification.objects.bulk_create(to_create)
            for notification in created:
                transaction.on_commit(
                    lambda n=notification: dispatch_notification.delay(n.id)
                )

        response_serializer = NotificationSerializer(created, many=True)
        return Response(
            {"count": len(created), "notifications": response_serializer.data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
