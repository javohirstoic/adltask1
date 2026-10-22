from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from analytics.services import timeline_bounds
from people.services import departments
from projects.models import Chat, Project

from . import appsettings, conf
from .models import DataVersion
from .permissions import ACCESS, ADMIN, BOSS, ROLE_LABELS, person_of, role_of, roles_required, scope_ids

WEB = Path(settings.BASE_DIR) / "web"


class PageView(LoginRequiredMixin, View):
    """Panel sahifalari (HTML): kirmagan foydalanuvchi /login ga yuboriladi; roli yo'qqa panel ochilmaydi."""
    page = "index.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and role_of(request.user) is None:
            return HttpResponseForbidden("Sizga panel roli berilmagan. Administratorga murojaat qiling. <a href='/login'>Kirish</a>")
        return super().dispatch(request, *args, **kwargs)

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return FileResponse(open(WEB / self.page, "rb"), content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


class LoginPageView(View):
    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return FileResponse(open(WEB / "login.html", "rb"), content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        user = authenticate(request, username=request.data.get("username", ""), password=request.data.get("password", ""))
        if user is None:
            return Response({"detail": "Login yoki parol noto'g'ri"}, status=401)
        if role_of(user) is None:
            return Response({"detail": "Sizga panel roli berilmagan. Administratorga murojaat qiling."}, status=403)
        login(request, user)
        return Response({"ok": True})


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"ok": True})


def _me(request) -> dict:
    user, role, person = request.user, role_of(request.user), person_of(request.user)
    return {"username": user.username, "name": person.name if person else (user.get_full_name() or user.username),
            "role": role, "role_label": ROLE_LABELS[role], "access": ACCESS[role]}


class MetaView(APIView):
    def get(self, request):
        ids = scope_ids(request)  # menejer faqat o'z loyihalari va ularning guruhlarini ko'radi
        projects, chats = Project.objects.order_by("name"), Chat.objects.order_by("demo", "title")
        if ids is not None:
            projects = projects.filter(id__in=ids)
            chats = chats.filter(id__in=Project.objects.filter(id__in=ids).values("chat_id"))
        return Response({
            "chats": list(chats.values("id", "title", "demo")),
            "projects": list(projects.values("id", "name", "chat_id")),
            "ai": conf.ai_enabled(), "bot": settings.BOT_USERNAME, "departments": departments(),
            "version": DataVersion.current(), "auth": True, "timeline": timeline_bounds(), "me": _me(request)})


class VersionView(APIView):
    def get(self, request):
        """Panel fayllari o'zgarsa brauzer o'zi yangilanadi (dizayn ustida ishlaganda jonli ko'rish uchun)."""
        ui = int(max(f.stat().st_mtime for f in WEB.iterdir() if f.is_file()))
        return Response({"v": DataVersion.current(), "ui": ui})


class SettingsView(APIView):
    def get_permissions(self):
        # o'qish — rahbar ham ko'radi, o'zgartirish faqat admin
        return [roles_required(ADMIN)() if self.request.method == "PUT" else roles_required(ADMIN, BOSS)()]

    def get(self, request):
        return Response({"values": appsettings.load(), "schema": appsettings.schema()})

    def put(self, request):
        try:
            values = appsettings.save(dict(request.data))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        DataVersion.bump()
        return Response({"values": values})
