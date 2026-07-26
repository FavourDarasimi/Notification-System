# Notification-System

## Authentication

This project uses **two distinct authentication mechanisms** — choose the right one depending on the caller.

### 1. User JWT (end-user sessions)

Used by the Next.js test client and any end-user-facing API calls.

- **Header:** `Authorization: Bearer <jwt>`
- **Get a token:** `POST /api/auth/login/` with `{"email": "...", "password": "..."}`
- **Refresh:** `POST /api/auth/token/refresh/` with `{"refresh": "<refresh_token>"}`
- **Backend:** `rest_framework_simplejwt.authentication.JWTAuthentication`
- **Config:** `SIMPLE_JWT` in `core/settings/base.py` — access token lifetime,
  refresh rotation, blacklist-after-rotation.
- **Default:** This is the **global default** — all views require a valid JWT
  unless marked with `AllowAny` or `IsServiceToken`.

### 2. Service Token (server-to-server)

Used exclusively by the notification creation endpoint so that trusted internal
services can push notifications without acting as a specific end-user.

- **Header:** `Authorization: Service <token>`
- **Get a token:** The token is a shared secret set via the `SERVICE_API_TOKEN`
  env var — there is no endpoint to obtain one.
- **Backend:** `apps.notifications.auth.ServiceTokenAuthentication`
- **Opt-in only:** This is **not** a global authentication class. Views that
  need it list it explicitly in their `authentication_classes` tuple alongside
  `JWTAuthentication`. The view then accepts *either* a user JWT *or* a
  service token.

### Choosing the right auth

| Caller | Auth type | Endpoint example |
|---|---|---|
| Next.js client (browser user) | JWT (Bearer) | `GET /api/notifications/`, `PATCH /api/notifications/{id}/read/` |
| Internal backend service | Service token | `POST /api/notifications/` (creation) |
| Celery task (async) | (none — runs internally) | `dispatch_notification`, `send_email_notification` |
