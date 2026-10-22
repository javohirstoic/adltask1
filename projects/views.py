from django.db.models import Count, Q

from core.api import DataViewSet, DeletableDataViewSet

from .models import Blocker, Chat, Message, Project, Task
from .serializers import BlockerSerializer, ChatSerializer, MessageSerializer, ProjectSerializer, TaskSerializer


class ChatViewSet(DataViewSet):
    resource = "chats"
    queryset = Chat.objects.annotate(projects_count=Count("projects", distinct=True), messages_count=Count("messages", distinct=True))
    serializer_class = ChatSerializer
    search_fields = ["title"]
    ordering_fields = ["title", "added_at", "projects_count", "messages_count"]
    ordering = ["demo", "title"]
    filter_params = {"demo": "demo"}

    def scope_queryset(self, qs, ids):
        # menejer faqat o'z loyihalari yozilgan guruhlarni ko'radi
        return qs.filter(id__in=Project.objects.filter(id__in=ids).values("chat_id"))


class ProjectViewSet(DataViewSet):
    resource = "projects"
    scope_lookup = "id"
    queryset = Project.objects.select_related("chat", "manager").annotate(
        open_tasks=Count("tasks", filter=Q(tasks__status="open"), distinct=True), total_tasks=Count("tasks", distinct=True))
    serializer_class = ProjectSerializer
    search_fields = ["name", "key", "aliases"]
    ordering_fields = ["name", "deadline", "created_at", "open_tasks", "total_tasks"]
    ordering = ["name"]
    filter_params = {"chat": "chat_id", "manager": "manager_id"}


class TaskViewSet(DataViewSet):
    resource = "tasks"
    scope_lookup = "project_id"
    queryset = Task.objects.select_related("project", "assignee")
    serializer_class = TaskSerializer
    search_fields = ["title", "assignee__name", "project__name"]
    ordering_fields = ["title", "created_at", "done_at", "deadline", "status"]
    ordering = ["-created_at", "-id"]
    filter_params = {"project": "project_id", "assignee": "assignee_id", "status": "status", "chat": "project__chat_id"}


class BlockerViewSet(DataViewSet):
    resource = "blockers"
    scope_lookup = "project_id"
    queryset = Blocker.objects.select_related("project", "author")
    serializer_class = BlockerSerializer
    search_fields = ["text", "project__name", "author__name"]
    ordering_fields = ["created_at", "resolved_at"]
    ordering = ["-created_at", "-id"]
    filter_params = {"project": "project_id", "author": "author_id"}

    def get_queryset(self):
        qs = super().get_queryset()
        resolved = self.request.query_params.get("resolved")
        if resolved in ("0", "1"):
            qs = qs.filter(resolved_at__isnull=(resolved == "0"))
        return qs


class MessageViewSet(DeletableDataViewSet):
    resource = "messages"
    scope_lookup = "project_id"
    queryset = Message.objects.select_related("chat", "user", "project")
    serializer_class = MessageSerializer
    search_fields = ["text", "user__name"]
    ordering_fields = ["date", "kind"]
    ordering = ["-date", "-id"]
    filter_params = {"chat": "chat_id", "kind": "kind", "project": "project_id", "user": "user_id", "source": "source"}
