from rest_framework import exceptions, status
from rest_framework.authentication import TokenAuthentication


BLOCKED_MESSAGE = "Hisobingiz bloklangan. Iltimos, ustoz bilan bog'laning."


class BlockedAuthenticationFailed(exceptions.AuthenticationFailed):
    """Bloklangan o'quvchi uchun 401 emas, 403 qaytaradi — frontend
    eskirgan tokenni (401) bloklanganidan (403) ajrata oladi."""

    status_code = status.HTTP_403_FORBIDDEN


class BlockAwareTokenAuthentication(TokenAuthentication):
    """Bloklangan o'quvchiga tegishli token bilan kirishni rad etadi."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if getattr(user, 'is_blocked', False):
            raise BlockedAuthenticationFailed(BLOCKED_MESSAGE)
        return user, token

