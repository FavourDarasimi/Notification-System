from django.urls import path

from . import views

urlpatterns = [
    path(
        "",
        views.NotificationListCreateView.as_view(),
        name="notification-list-create",
    ),
    path(
        "unread-count/",
        views.NotificationUnreadCountView.as_view(),
        name="notification-unread-count",
    ),
    path(
        "mark-all-read/",
        views.NotificationMarkAllReadView.as_view(),
        name="notification-mark-all-read",
    ),
    path(
        "preferences/",
        views.NotificationPreferenceView.as_view(),
        name="notification-preferences",
    ),
    path(
        "<uuid:id>/read/",
        views.NotificationReadView.as_view(),
        name="notification-read",
    ),
    path(
        "<uuid:id>/",
        views.NotificationDeleteView.as_view(),
        name="notification-delete",
    ),
]
