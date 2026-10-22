from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("decisions", views.DecisionViewSet)
router.register("alerts", views.AlertViewSet)

urlpatterns = [
    path("api/actions/preview", views.PreviewView.as_view()),
    path("api/actions/execute", views.ExecuteView.as_view()),
    path("api/messages/<int:mid>/correct", views.CorrectView.as_view()),
    path("api/data/", include(router.urls)),
]
