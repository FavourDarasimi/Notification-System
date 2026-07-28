"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.db import connections
from django.http import JsonResponse
from django.urls import include, path

from apps.notifications.views import PusherAuthView


def healthz(request):
    db_ok = False
    try:
        connections["default"].cursor()
        db_ok = True
    except Exception:
        pass
    status_code = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "unavailable"}, status=status_code)


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.users.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/pusher/auth/", PusherAuthView.as_view(), name="pusher-auth"),
]
