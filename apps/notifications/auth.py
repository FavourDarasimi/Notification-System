from django.contrib.auth import get_user_model
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed


class ServiceTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate via a shared service token for server-to-server calls.

    Header format::
        Authorization: Service <token>

    This is distinct from user JWT auth (``Authorization: Bearer <jwt>``).

    - User JWT auth identifies a specific end-user via ``JWTAuthentication``.
    - Service token auth identifies the calling backend service, not any
      particular user.  The returned user is a dedicated internal service
      account (``username='__service__'``, created on first use).

    Use this auth class on views that only trusted internal services should
    call (e.g. the notification creation endpoint).  It should be listed
    *alongside* ``JWTAuthentication`` so that the same view can accept
    either credential type when appropriate.
    """

    keyword = "Service"

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request)
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) == 1:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed(
                "Authorization header must have two parts."
            )

        keyword, token = parts[0].decode(), parts[1].decode()
        if keyword.lower() != self.keyword.lower():
            return None

        if token != self._get_service_token():
            raise AuthenticationFailed("Invalid service token.")

        service_user, _ = get_user_model().objects.get_or_create(
            username="__service__",
            defaults={
                "email": "service@internal.local",
                "is_active": True,
            },
        )
        return (service_user, token)

    @staticmethod
    def _get_service_token():
        from django.conf import settings

        token = settings.SERVICE_API_TOKEN
        if not token:
            raise AuthenticationFailed(
                "Service API token is not configured (SERVICE_API_TOKEN)."
            )
        return token
