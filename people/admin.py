from django.contrib import admin

from .models import Department, Person


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("name", "username", "department", "role", "telegram_id")
    list_filter = ("department", "role")
    search_fields = ("name", "username")


admin.site.register(Department)
