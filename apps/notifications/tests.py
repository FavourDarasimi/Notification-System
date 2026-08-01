from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import DeliveryLog, Notification, NotificationType, Room, RoomMember


def assert_unauthorized(response):
    """Accept either 401 or 403 — both indicate the request was rejected."""
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ), f"Expected 401 or 403, got {response.status_code}: {response.content}"


@override_settings(SERVICE_API_TOKEN="test-service-token")
class NotificationAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ntype = NotificationType.objects.create(
            key="test_type",
            name="Test Type",
            default_channels=["in_app"],
        )
        cls.ntype2 = NotificationType.objects.create(
            key="other_type",
            name="Other Type",
            default_channels=["in_app"],
        )

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user_a = User.objects.create_user(
            email="a@test.com", password="pass", username="user_a"
        )
        self.user_b = User.objects.create_user(
            email="b@test.com", password="pass", username="user_b"
        )
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)
        self.service_client = APIClient()
        self.service_client.credentials(
            HTTP_AUTHORIZATION="Service test-service-token"
        )
        self.anon_client = APIClient()

        # Seed a notification for user_a
        self.notif_a = Notification.objects.create(
            recipient=self.user_a,
            notification_type=self.ntype,
            message="Hello A",
        )
        # And one for user_b
        self.notif_b = Notification.objects.create(
            recipient=self.user_b,
            notification_type=self.ntype2,
            message="Hello B",
        )

    # --- Notification List (GET /api/notifications/) ---

    def test_list_returns_only_own_notifications(self):
        r = self.client_a.get("/api/notifications/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get("results", r.data)
        ids = [n["id"] for n in results]
        self.assertIn(str(self.notif_a.id), ids)
        self.assertNotIn(str(self.notif_b.id), ids)

    def test_list_requires_auth(self):
        r = self.anon_client.get("/api/notifications/")
        assert_unauthorized(r)

    def test_list_filter_by_is_read(self):
        Notification.objects.create(
            recipient=self.user_a,
            notification_type=self.ntype,
            message="Unread",
            is_read=False,
        )
        Notification.objects.create(
            recipient=self.user_a,
            notification_type=self.ntype,
            message="Read",
            is_read=True,
        )

        r = self.client_a.get("/api/notifications/?is_read=true")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get("results", r.data)
        self.assertTrue(all(n["is_read"] for n in results))

        r = self.client_a.get("/api/notifications/?is_read=false")
        results = r.data.get("results", r.data)
        self.assertTrue(all(not n["is_read"] for n in results))

    def test_list_filter_by_notification_type(self):
        r = self.client_a.get(
            f"/api/notifications/?notification_type={self.ntype.key}"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get("results", r.data)
        for n in results:
            self.assertEqual(n["notification_type"], self.ntype.key)

    # --- Unread Count (GET /api/notifications/unread-count/) ---

    def test_unread_count_is_user_scoped(self):
        r = self.client_a.get("/api/notifications/unread-count/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)  # notif_a is unread

        # Mark user_a's notification as read
        Notification.objects.filter(recipient=self.user_a).update(is_read=True)
        r = self.client_a.get("/api/notifications/unread-count/")
        self.assertEqual(r.data["count"], 0)

        # user_b's unread count should be unaffected
        r = self.client_b.get("/api/notifications/unread-count/")
        self.assertEqual(r.data["count"], 1)  # notif_b is still unread

    def test_unread_count_requires_auth(self):
        r = self.anon_client.get("/api/notifications/unread-count/")
        assert_unauthorized(r)

    # --- Mark Read (PATCH /api/notifications/{id}/read/) ---

    def test_mark_read_own_notification(self):
        r = self.client_a.patch(
            f"/api/notifications/{self.notif_a.id}/read/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["is_read"])
        self.assertIsNotNone(r.data["read_at"])

    def test_mark_read_other_users_notification_returns_404(self):
        r = self.client_a.patch(
            f"/api/notifications/{self.notif_b.id}/read/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_read_requires_auth(self):
        r = self.anon_client.patch(
            f"/api/notifications/{self.notif_a.id}/read/"
        )
        assert_unauthorized(r)

    # --- Mark All Read (POST /api/notifications/mark-all-read/) ---

    def test_mark_all_read_only_affects_own(self):
        Notification.objects.create(
            recipient=self.user_a,
            notification_type=self.ntype,
            message="A another",
        )
        r = self.client_a.post("/api/notifications/mark-all-read/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["updated"], 2)  # notif_a + the new one

        # user_b's notifications remain unread
        self.assertFalse(
            Notification.objects.get(id=self.notif_b.id).is_read
        )

    def test_mark_all_read_requires_auth(self):
        r = self.anon_client.post("/api/notifications/mark-all-read/")
        assert_unauthorized(r)

    # --- Delete (DELETE /api/notifications/{id}/) ---

    def test_delete_own_notification(self):
        r = self.client_a.delete(
            f"/api/notifications/{self.notif_a.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            Notification.objects.filter(id=self.notif_a.id).exists()
        )

    def test_delete_other_users_notification_returns_404(self):
        r = self.client_a.delete(
            f"/api/notifications/{self.notif_b.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(
            Notification.objects.filter(id=self.notif_b.id).exists()
        )

    def test_delete_requires_auth(self):
        r = self.anon_client.delete(
            f"/api/notifications/{self.notif_a.id}/"
        )
        assert_unauthorized(r)

    # --- Create (POST /api/notifications/) ---

    def test_create_single_with_service_token(self):
        r = self.service_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "Single notification",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["message"], "Single notification")
        self.assertEqual(
            r.data["notification_type"], self.ntype.key
        )

    def test_create_without_service_token_returns_401(self):
        r = self.anon_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "No service token",
            },
            format="json",
        )
        assert_unauthorized(r)

    def test_create_with_invalid_service_token_returns_401(self):
        bad_client = APIClient()
        bad_client.credentials(HTTP_AUTHORIZATION="Service wrong-token")
        r = bad_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "Bad token",
            },
            format="json",
        )
        assert_unauthorized(r)

    def test_create_idempotent_returns_existing(self):
        key = "dup-key-1"
        r1 = self.service_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "First",
                "idempotency_key": key,
            },
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        first_id = r1.data["id"]

        r2 = self.service_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "Second (should be ignored)",
                "idempotency_key": key,
            },
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data["id"], first_id)
        self.assertEqual(r2.data["message"], "First")  # original preserved

    def test_create_bulk(self):
        r = self.service_client.post(
            "/api/notifications/",
            {
                "notifications": [
                    {
                        "recipient_id": self.user_a.id,
                        "notification_type_key": self.ntype.key,
                        "message": "Bulk 1",
                    },
                    {
                        "recipient_id": self.user_b.id,
                        "notification_type_key": self.ntype2.key,
                        "message": "Bulk 2",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(r.data), 2)
        messages = {n["message"] for n in r.data}
        self.assertEqual(messages, {"Bulk 1", "Bulk 2"})

    def test_create_bulk_with_mixed_idempotency(self):
        key = "bulk-dup"
        self.service_client.post(
            "/api/notifications/",
            {
                "recipient_id": self.user_a.id,
                "notification_type_key": self.ntype.key,
                "message": "Original",
                "idempotency_key": key,
            },
            format="json",
        )
        r = self.service_client.post(
            "/api/notifications/",
            {
                "notifications": [
                    {
                        "recipient_id": self.user_a.id,
                        "notification_type_key": self.ntype.key,
                        "message": "Existing",
                        "idempotency_key": key,
                    },
                    {
                        "recipient_id": self.user_b.id,
                        "notification_type_key": self.ntype2.key,
                        "message": "New",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(r.data), 2)
        messages = {n["message"] for n in r.data}
        self.assertEqual(messages, {"Original", "New"})

    def test_create_invalid_data_returns_400(self):
        r = self.service_client.post(
            "/api/notifications/",
            {"recipient_id": 99999, "notification_type_key": "nonexistent"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("apps.notifications.services.pusher_client.publish_notification_event")
    def test_create_creates_delivery_log(self, mock_publish):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.service_client.post(
                "/api/notifications/",
                {
                    "recipient_id": self.user_a.id,
                    "notification_type_key": self.ntype.key,
                    "message": "Delivery log test",
                },
                format="json",
            )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        notification = Notification.objects.get(id=r.data["id"])
        log = DeliveryLog.objects.get(
            notification=notification,
            channel="in_app",
        )
        self.assertEqual(log.status, "sent")


class NotificationPreferenceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ntype_a = NotificationType.objects.create(
            key="comment_reply",
            name="Comment Reply",
            default_channels=["in_app", "email"],
        )
        cls.ntype_b = NotificationType.objects.create(
            key="system_alert",
            name="System Alert",
            default_channels=["in_app"],
        )

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            email="pref@test.com", password="pass", username="pref_user"
        )
        self.other = User.objects.create_user(
            email="other@test.com", password="pass", username="other_user"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)
        self.anon_client = APIClient()

    # --- GET /api/notifications/preferences/ ---

    def test_get_returns_all_types_with_defaults(self):
        r = self.client.get("/api/notifications/preferences/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = {p["notification_type"]: p for p in r.data}

        self.assertIn("comment_reply", data)
        self.assertEqual(data["comment_reply"]["in_app"], True)
        self.assertEqual(data["comment_reply"]["email"], True)

        self.assertIn("system_alert", data)
        self.assertEqual(data["system_alert"]["in_app"], True)
        self.assertEqual(data["system_alert"]["email"], False)

    def test_get_auto_creates_for_new_type(self):
        NotificationType.objects.create(
            key="welcome", name="Welcome", default_channels=["email"]
        )

        r = self.client.get("/api/notifications/preferences/")
        data = {p["notification_type"]: p for p in r.data}

        self.assertIn("welcome", data)
        self.assertEqual(data["welcome"]["in_app"], False)
        self.assertEqual(data["welcome"]["email"], True)

    def test_get_requires_auth(self):
        r = self.anon_client.get("/api/notifications/preferences/")
        assert_unauthorized(r)

    def test_get_is_user_scoped(self):
        r = self.client.get("/api/notifications/preferences/")
        my_data = {p["notification_type"]: p for p in r.data}

        r2 = self.other_client.get("/api/notifications/preferences/")
        other_data = {p["notification_type"]: p for p in r2.data}

        self.assertEqual(set(my_data.keys()), set(other_data.keys()))
        self.assertEqual(my_data["comment_reply"]["email"], True)
        self.assertEqual(other_data["comment_reply"]["email"], True)

    # --- PUT /api/notifications/preferences/ ---

    def test_put_updates_existing_preference(self):
        r = self.client.put(
            "/api/notifications/preferences/",
            [
                {
                    "notification_type_key": "comment_reply",
                    "email": False,
                }
            ],
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = {p["notification_type"]: p for p in r.data}
        self.assertEqual(data["comment_reply"]["email"], False)
        self.assertEqual(data["comment_reply"]["in_app"], True)  # unchanged

    def test_put_creates_missing_preference_row(self):
        NotificationType.objects.create(
            key="welcome", name="Welcome", default_channels=["email"]
        )

        r = self.client.put(
            "/api/notifications/preferences/",
            [
                {
                    "notification_type_key": "welcome",
                    "in_app": True,
                    "email": True,
                }
            ],
            format="json",
        )
        data = {p["notification_type"]: p for p in r.data}
        self.assertEqual(data["welcome"]["in_app"], True)
        self.assertEqual(data["welcome"]["email"], True)

    def test_put_partial_update_keeps_other_fields(self):
        r = self.client.put(
            "/api/notifications/preferences/",
            [
                {
                    "notification_type_key": "comment_reply",
                    "in_app": False,
                }
            ],
            format="json",
        )
        data = {p["notification_type"]: p for p in r.data}
        # in_app was changed, email should still be True from defaults
        self.assertEqual(data["comment_reply"]["in_app"], False)
        self.assertEqual(data["comment_reply"]["email"], True)

    def test_put_invalid_notification_type_returns_400(self):
        r = self.client.put(
            "/api/notifications/preferences/",
            [{"notification_type_key": "nonexistent"}],
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_requires_auth(self):
        r = self.anon_client.put(
            "/api/notifications/preferences/",
            [{"notification_type_key": "comment_reply"}],
            format="json",
        )
        assert_unauthorized(r)


from unittest.mock import patch


class PusherAuthTestCase(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user_a = User.objects.create_user(
            email="pa@test.com", password="pass", username="pusher_a"
        )
        self.user_b = User.objects.create_user(
            email="pb@test.com", password="pass", username="pusher_b"
        )
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)
        self.anon_client = APIClient()

    @patch("apps.notifications.views.pusher.Pusher")
    def test_auth_own_channel(self, mock_pusher):
        mock_pusher.return_value.authenticate.return_value = {
            "auth": "signed:abc123"
        }
        r = self.client_a.post(
            "/api/pusher/auth/",
            {
                "channel_name": f"private-user-{self.user_a.id}",
                "socket_id": "1234.5678",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data, {"auth": "signed:abc123"})
        mock_pusher.return_value.authenticate.assert_called_once_with(
            channel=f"private-user-{self.user_a.id}",
            socket_id="1234.5678",
        )

    @patch("apps.notifications.views.pusher.Pusher")
    def test_auth_other_users_channel_returns_403(self, mock_pusher):
        r = self.client_a.post(
            "/api/pusher/auth/",
            {
                "channel_name": f"private-user-{self.user_b.id}",
                "socket_id": "1234.5678",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        mock_pusher.return_value.authenticate.assert_not_called()

    def test_auth_requires_jwt(self):
        r = self.anon_client.post(
            "/api/pusher/auth/",
            {
                "channel_name": "private-user-1",
                "socket_id": "1234.5678",
            },
            format="json",
        )
        assert_unauthorized(r)

    def test_auth_missing_params_returns_400(self):
        r = self.client_a.post(
            "/api/pusher/auth/",
            {"channel_name": "private-user-1"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        r = self.client_a.post(
            "/api/pusher/auth/",
            {"socket_id": "1234.5678"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TaskTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ntype = NotificationType.objects.create(
            key="task_type",
            name="Task Type",
            default_channels=["in_app", "email"],
        )

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            email="task@test.com", password="pass", username="task_user"
        )

    def test_send_email_creates_delivery_log(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=self.ntype,
            message="Email test",
        )

        from .tasks import send_email_notification

        send_email_notification.delay(notification.id)

        log = DeliveryLog.objects.get(
            notification=notification,
            channel="email",
        )
        self.assertEqual(log.status, "sent")

    def test_cleanup_removes_old_notifications(self):
        old = Notification.objects.create(
            recipient=self.user,
            notification_type=self.ntype,
            message="Old notification",
        )
        Notification.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(days=100)
        )

        recent = Notification.objects.create(
            recipient=self.user,
            notification_type=self.ntype,
            message="Recent notification",
        )

        from .tasks import cleanup_old_notifications

        cleanup_old_notifications.delay()

        self.assertFalse(Notification.objects.filter(id=old.id).exists())
        self.assertTrue(Notification.objects.filter(id=recent.id).exists())


@override_settings(
    DJANGO_ENABLE_TEST_ENDPOINTS=True,
    CELERY_TASK_ALWAYS_EAGER=True,
)
class NotificationTestEndpointTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ntype = NotificationType.objects.create(
            key="test_type",
            name="Test Type",
            default_channels=["in_app"],
        )

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            email="trigger@test.com", password="pass", username="trigger_user"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.anon_client = APIClient()

    @patch("apps.notifications.services.pusher_client.publish_notification_event")
    def test_create_self_notification_goes_through_dispatch(self, mock_publish):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(
                "/api/notifications/test/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "Triggered by me",
                },
                format="json",
            )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["recipient"], self.user.id)
        self.assertEqual(r.data["message"], "Triggered by me")

        notification = Notification.objects.get(id=r.data["id"])
        log = DeliveryLog.objects.get(
            notification=notification,
            channel="in_app",
        )
        self.assertEqual(log.status, "sent")

    def test_disabled_returns_404(self):
        with override_settings(DJANGO_ENABLE_TEST_ENDPOINTS=False):
            r = self.client.post(
                "/api/notifications/test/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "Nope",
                },
                format="json",
            )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_auth(self):
        r = self.anon_client.post(
            "/api/notifications/test/",
            {
                "notification_type_key": self.ntype.key,
                "message": "Anon",
            },
            format="json",
        )
        assert_unauthorized(r)

    def test_invalid_type_returns_400(self):
        r = self.client.post(
            "/api/notifications/test/",
            {
                "notification_type_key": "does_not_exist",
                "message": "Bad",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RoomTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ntype = NotificationType.objects.create(
            key="room_type",
            name="Room Type",
            default_channels=["in_app"],
        )

    def setUp(self):
        from django.contrib.auth import get_user_model

        patcher = patch(
            "apps.notifications.services.pusher_client.publish_notification_event"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        User = get_user_model()
        self.user_a = User.objects.create_user(
            email="room_a@test.com", password="pass", username="room_a"
        )
        self.user_b = User.objects.create_user(
            email="room_b@test.com", password="pass", username="room_b"
        )
        self.user_c = User.objects.create_user(
            email="room_c@test.com", password="pass", username="room_c"
        )
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)
        self.client_c = APIClient()
        self.client_c.force_authenticate(user=self.user_c)
        self.anon_client = APIClient()

        self.room = Room.objects.create(
            slug="general",
            name="General",
            description="Everything",
            created_by=self.user_a,
        )
        RoomMember.objects.create(room=self.room, user=self.user_a)
        RoomMember.objects.create(room=self.room, user=self.user_b)

    # --- Create (POST /api/rooms/) ---

    def test_create_room_auto_joins_creator(self):
        r = self.client_a.post(
            "/api/rooms/",
            {"name": "New Room"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["slug"], "new-room")
        self.assertTrue(r.data["is_member"])
        self.assertEqual(r.data["member_count"], 1)
        self.assertTrue(
            RoomMember.objects.filter(
                room__slug="new-room", user=self.user_a
            ).exists()
        )

    def test_create_room_with_custom_slug(self):
        r = self.client_a.post(
            "/api/rooms/",
            {"name": "Other", "slug": "custom-slug"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["slug"], "custom-slug")

    def test_create_room_slug_collision_appends_suffix(self):
        r1 = self.client_a.post(
            "/api/rooms/",
            {"name": "General"},
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r1.data["slug"], "general-2")

        r2 = self.client_a.post(
            "/api/rooms/",
            {"name": "General"},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.data["slug"], "general-3")

    def test_create_room_requires_auth(self):
        r = self.anon_client.post(
            "/api/rooms/", {"name": "Nope"}, format="json"
        )
        assert_unauthorized(r)

    # --- List (GET /api/rooms/) ---

    def test_list_shows_all_rooms_with_membership(self):
        r = self.client_b.get("/api/rooms/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        by_slug = {room["slug"]: room for room in r.data}
        self.assertIn("general", by_slug)
        self.assertTrue(by_slug["general"]["is_member"])
        self.assertEqual(by_slug["general"]["member_count"], 2)

        r = self.client_c.get("/api/rooms/")
        by_slug = {room["slug"]: room for room in r.data}
        self.assertFalse(by_slug["general"]["is_member"])

    def test_list_requires_auth(self):
        r = self.anon_client.get("/api/rooms/")
        assert_unauthorized(r)

    # --- Join / Leave ---

    def test_join_is_idempotent(self):
        r1 = self.client_c.post("/api/rooms/general/join/")
        r2 = self.client_c.post("/api/rooms/general/join/")
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(
            RoomMember.objects.filter(
                room=self.room, user=self.user_c
            ).count(),
            1,
        )

    def test_leave_removes_membership(self):
        self.client_b.post("/api/rooms/general/leave/")
        self.assertFalse(
            RoomMember.objects.filter(
                room=self.room, user=self.user_b
            ).exists()
        )

    def test_leave_is_idempotent(self):
        r = self.client_c.post("/api/rooms/general/leave/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_join_requires_auth(self):
        r = self.anon_client.post("/api/rooms/general/join/")
        assert_unauthorized(r)

    # --- Detail (GET /api/rooms/<slug>/) ---

    def test_detail_returns_room_and_members(self):
        r = self.client_c.get("/api/rooms/general/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["room"]["slug"], "general")
        emails = {m["email"] for m in r.data["members"]}
        self.assertEqual(emails, {"room_a@test.com", "room_b@test.com"})

    def test_detail_unknown_room_returns_404(self):
        r = self.client_a.get("/api/rooms/nope/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    # --- Send (POST /api/rooms/<slug>/send/) ---

    def test_send_fans_out_to_other_members(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client_a.post(
                "/api/rooms/general/send/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "Hello room",
                },
                format="json",
            )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["count"], 1)

        n = Notification.objects.get(recipient=self.user_b)
        self.assertEqual(n.message, "Hello room")
        self.assertEqual(n.room, self.room)
        self.assertEqual(n.actor, self.user_a)
        self.assertEqual(n.recipient, self.user_b)

        # Sender must NOT receive their own room notification.
        self.assertFalse(
            Notification.objects.filter(recipient=self.user_a).exists()
        )

    def test_send_to_all_members_when_three_joined(self):
        RoomMember.objects.create(room=self.room, user=self.user_c)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client_a.post(
                "/api/rooms/general/send/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "To all",
                },
                format="json",
            )
        self.assertEqual(r.data["count"], 2)
        recipients = set(
            Notification.objects.filter(room=self.room).values_list(
                "recipient_id", flat=True
            )
        )
        self.assertEqual(recipients, {self.user_b.id, self.user_c.id})

    def test_send_with_no_other_members_returns_empty(self):
        RoomMember.objects.filter(room=self.room, user=self.user_b).delete()
        r = self.client_a.post(
            "/api/rooms/general/send/",
            {
                "notification_type_key": self.ntype.key,
                "message": "Lonely",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)
        self.assertEqual(r.data["notifications"], [])

    def test_send_by_non_member_returns_403(self):
        r = self.client_c.post(
            "/api/rooms/general/send/",
            {
                "notification_type_key": self.ntype.key,
                "message": "Not a member",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Notification.objects.filter(message="Not a member").exists()
        )

    def test_send_requires_auth(self):
        r = self.anon_client.post(
            "/api/rooms/general/send/",
            {
                "notification_type_key": self.ntype.key,
                "message": "Anon",
            },
            format="json",
        )
        assert_unauthorized(r)

    def test_send_invalid_type_returns_400(self):
        r = self.client_a.post(
            "/api/rooms/general/send/",
            {"notification_type_key": "nope", "message": "Bad"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_is_idempotent_per_recipient(self):
        key = "room-dup"
        with self.captureOnCommitCallbacks(execute=True):
            r1 = self.client_a.post(
                "/api/rooms/general/send/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "First",
                    "idempotency_key": key,
                },
                format="json",
            )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)

        with self.captureOnCommitCallbacks(execute=True):
            r2 = self.client_a.post(
                "/api/rooms/general/send/",
                {
                    "notification_type_key": self.ntype.key,
                    "message": "Duplicate",
                    "idempotency_key": key,
                },
                format="json",
            )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data["count"], 0)
        self.assertEqual(
            Notification.objects.filter(recipient=self.user_b).count(), 1
        )
        self.assertEqual(
            Notification.objects.get(recipient=self.user_b).message, "First"
        )

    # --- Room filter on notifications list ---

    def test_list_filters_by_room(self):
        Notification.objects.create(
            recipient=self.user_b,
            notification_type=self.ntype,
            room=self.room,
            message="In room",
        )
        Notification.objects.create(
            recipient=self.user_b,
            notification_type=self.ntype,
            message="Not in room",
        )
        r = self.client_b.get("/api/notifications/?room=general")
        results = r.data.get("results", r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["message"], "In room")
        self.assertEqual(results[0]["room"], "general")
