from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import ServiceTokenAuthentication
from .filters import NotificationFilter
from .models import Notification, NotificationPreference, NotificationType
from .pagination import NotificationCursorPagination
from .serializers import (
    BulkNotificationCreateSerializer,
    NotificationCreateSerializer,
    NotificationPreferenceReadSerializer,
    NotificationPreferenceWriteItemSerializer,
    NotificationSerializer,
)


class NotificationListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    filterset_class = NotificationFilter

    def get_authenticators(self):
        if self.request.method == "POST":
            return [ServiceTokenAuthentication()]
        from rest_framework_simplejwt.authentication import JWTAuthentication

        return [JWTAuthentication()]

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

        results = self._perform_create(items)
        any_new = any(
            not hasattr(n, "_existing") for n in results
        )

        if is_bulk:
            serializer = NotificationSerializer(results, many=True)
        else:
            serializer = NotificationSerializer(results[0])

        status_code = status.HTTP_201_CREATED if any_new else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)

    def _perform_create(self, items):
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
            created = Notification.objects.bulk_create(to_create)
            results.extend(created)
            # TODO: Phase 4 — dispatch Celery tasks for each created notification
            # for notification in created:
            #     transaction.on_commit(lambda n=notification: dispatch_notification.delay(n.id))

        return results


class NotificationUnreadCountView(APIView):
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
