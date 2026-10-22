from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("departments", views.DepartmentViewSet)
router.register("people", views.PersonViewSet)

urlpatterns = [
    path("api/person/department", views.DepartmentView.as_view()),
    path("api/person/role", views.RoleView.as_view()),
    path("api/person/name", views.NameView.as_view()),
    path("api/person/link", views.LinkView.as_view()),
    path("api/person/link/reset", views.LinkResetView.as_view()),
    path("api/links", views.LinksView.as_view()),
    path("api/data/", include(router.urls)),
]
