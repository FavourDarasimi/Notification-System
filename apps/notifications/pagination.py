from rest_framework.pagination import CursorPagination


class NotificationCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20
