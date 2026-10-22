from rest_framework.authentication import SessionAuthentication


class SessionAuth401(SessionAuthentication):
    """Kirmagan foydalanuvchiga 403 emas, 401 qaytaradi: panel shunga qarab kirish sahifasiga o'tadi."""

    def authenticate_header(self, request):
        return "Session"
