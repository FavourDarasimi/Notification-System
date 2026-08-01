from django.urls import path

from . import views

urlpatterns = [
    path(
        "",
        views.RoomListCreateView.as_view(),
        name="room-list-create",
    ),
    path(
        "<slug:slug>/send/",
        views.RoomSendView.as_view(),
        name="room-send",
    ),
    path(
        "<slug:slug>/join/",
        views.RoomJoinView.as_view(),
        name="room-join",
    ),
    path(
        "<slug:slug>/leave/",
        views.RoomLeaveView.as_view(),
        name="room-leave",
    ),
    path(
        "<slug:slug>/",
        views.RoomDetailView.as_view(),
        name="room-detail",
    ),
]
