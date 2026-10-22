from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("chats", views.ChatViewSet)
router.register("projects", views.ProjectViewSet)
router.register("tasks", views.TaskViewSet)
router.register("blockers", views.BlockerViewSet)
router.register("messages", views.MessageViewSet)

urlpatterns = [path("api/data/", include(router.urls))]
