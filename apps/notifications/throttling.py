from rest_framework.throttling import UserRateThrottle


class NotificationsListThrottle(UserRateThrottle):
    scope = "notifications_list"


class NotificationsTestThrottle(UserRateThrottle):
    scope = "notifications_test"
