from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("people.urls")),
    path("", include("analytics.urls")),
    path("", include("actions.urls")),
    path("", include("projects.urls")),
    path("", include("reports.urls")),
    path("", include("ingest.urls")),
]
