from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("corrections", views.CorrectionViewSet)

urlpatterns = [
    path("api/import", views.ImportView.as_view()),
    path("api/data/", include(router.urls)),
]
