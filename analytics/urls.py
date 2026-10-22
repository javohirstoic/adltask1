from django.urls import path

from . import views

urlpatterns = [
    path("api/summary", views.SummaryView.as_view()),
    path("api/project/<int:pid>", views.ProjectDetailView.as_view()),
    path("api/person", views.PersonDetailView.as_view()),
]
