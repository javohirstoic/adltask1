from django.http import HttpResponse
from django.urls import path

from . import views

urlpatterns = [
    path("", views.PageView.as_view(), name="index"),
    path("taqdimot", views.PageView.as_view(page="taqdimot.html"), name="slides"),
    path("login", views.LoginPageView.as_view(), name="login"),
    path("favicon.ico", lambda request: HttpResponse(status=204)),
    path("api/login", views.LoginView.as_view()),
    path("api/logout", views.LogoutView.as_view()),
    path("api/meta", views.MetaView.as_view()),
    path("api/version", views.VersionView.as_view()),
    path("api/settings", views.SettingsView.as_view()),
]
