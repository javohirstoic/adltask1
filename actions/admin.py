from django.contrib import admin

from .models import Alert, Decision


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "type", "title", "origin", "sent")
    list_filter = ("type", "origin")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "assignee", "resolution", "resolved_by")
    list_filter = ("kind",)
