from django.urls import path

from . import views

urlpatterns = [path("api/export.xlsx", views.ExportView.as_view())]
