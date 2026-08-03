from rest_framework.throttling import SimpleRateThrottle


class AuthThrottle(SimpleRateThrottle):
    """Register/login endpoint'larini IP bo'yicha tezlik cheklovi.

    Brute-force hujumlarini sekinlashtirish uchun. Tezlik `REST_FRAMEWORK`
    sozlamalaridagi `DEFAULT_THROTTLE_RATES['auth']` dan olinadi.
    """

    scope = 'auth'

    def get_cache_key(self, request, view):
        # Register/login vaqtida foydalanuvchi hali anonim — IP bo'yicha
        # hisoblaymiz (AnonRateThrottle kabi).
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
