from django.contrib import admin

from .models import Blocker, Chat, Message, Project, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "assignee", "status", "created_at", "done_at", "deadline")
    list_filter = ("status", "project")
    search_fields = ("title",)
    raw_id_fields = ("assignee", "created_msg", "done_msg")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("date", "chat", "user", "kind", "source", "project")
    list_filter = ("kind", "source", "chat")
    search_fields = ("text",)
    raw_id_fields = ("user",)


admin.site.register(Chat)
admin.site.register(Project)
admin.site.register(Blocker)
