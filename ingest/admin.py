from django.contrib import admin

from .models import Correction, DemoQueueItem


@admin.register(Correction)
class CorrectionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "old_kind", "new_kind", "old_project", "new_project", "text")


admin.site.register(DemoQueueItem)
