from rest_framework import serializers

from core import conf
from core.permissions import scope_ids
from people.models import Person
from ingest.parser import norm_key

from .models import Blocker, Chat, Message, Project, Task


class ScopedProjectMixin:
    """Menejer vazifa yoki muammoni faqat o'z loyihasiga yoza oladi (boshqasiga ko'chira ham olmaydi)."""

    def validate_project(self, project):
        request = self.context.get("request")
        ids = scope_ids(request) if request else None
        if ids is not None and project.id not in ids:
            raise serializers.ValidationError("Bu loyiha sizga biriktirilmagan")
        return project


class ChatSerializer(serializers.ModelSerializer):
    projects_count = serializers.IntegerField(read_only=True)
    messages_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Chat
        fields = ["id", "title", "demo", "added_at", "projects_count", "messages_count"]
        read_only_fields = ["added_at"]

    def create(self, data):
        data["added_at"] = conf.now()
        return super().create(data)

    def update(self, instance, data):
        data.pop("id", None)  # Telegram chat id o'zgarmaydi
        return super().update(instance, data)


class ProjectSerializer(serializers.ModelSerializer):
    chat_title = serializers.CharField(source="chat.title", read_only=True, allow_null=True)
    manager_name = serializers.CharField(source="manager.name", read_only=True, allow_null=True)
    open_tasks = serializers.IntegerField(read_only=True)
    total_tasks = serializers.IntegerField(read_only=True)
    key = serializers.CharField(required=False, allow_blank=True, max_length=80)

    class Meta:
        model = Project
        fields = ["id", "key", "name", "aliases", "chat", "chat_title", "manager", "manager_name", "deadline", "created_at",
                  "open_tasks", "total_tasks"]
        read_only_fields = ["created_at"]

    def validate_manager(self, person):
        if person is not None and person.role != Person.Role.MANAGER:
            raise serializers.ValidationError("«Loyiha menejeri» roli berilgan xodimni tanlang")
        return person

    def validate(self, data):
        key = norm_key(data.get("key") or "")
        if not key and self.instance is None:
            key = norm_key(data.get("name", ""))
        if self.instance is None and not key:
            raise serializers.ValidationError({"name": "Nomida kamida bitta harf yoki raqam bo'lsin"})
        if key:
            if Project.objects.filter(key=key).exclude(id=self.instance.id if self.instance else None).exists():
                raise serializers.ValidationError({"key": "Bu teg band"})
            data["key"] = key
        else:
            data.pop("key", None)
        return data

    def create(self, data):
        data["created_at"] = conf.now()
        return super().create(data)


class TaskSerializer(ScopedProjectMixin, serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    assignee_name = serializers.CharField(source="assignee.name", read_only=True, allow_null=True)

    class Meta:
        model = Task
        fields = ["id", "project", "project_name", "title", "assignee", "assignee_name", "status", "created_at", "done_at", "deadline"]
        read_only_fields = ["created_at", "done_at"]

    def create(self, data):
        now = conf.now()
        data["created_at"] = now
        if data.get("status") == "done":
            data["done_at"] = now
        return super().create(data)

    def update(self, instance, data):
        status = data.get("status")
        if status == "done" and instance.status != "done":
            data["done_at"] = conf.now()
        elif status in ("open", "taklif"):
            data["done_at"] = None
        return super().update(instance, data)


class BlockerSerializer(ScopedProjectMixin, serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    author_name = serializers.CharField(source="author.name", read_only=True, allow_null=True)
    resolved = serializers.BooleanField(required=False)  # yozilganda resolved_at ni belgilaydi

    class Meta:
        model = Blocker
        fields = ["id", "project", "project_name", "text", "author", "author_name", "created_at", "resolved_at", "resolved"]
        read_only_fields = ["created_at", "resolved_at"]

    def to_representation(self, obj):
        out = super().to_representation(obj)
        out["resolved"] = obj.resolved_at is not None
        return out

    def create(self, data):
        resolved = data.pop("resolved", False)
        now = conf.now()
        data["created_at"] = now
        data["resolved_at"] = now if resolved else None
        return super().create(data)

    def update(self, instance, data):
        if "resolved" in data:
            resolved = data.pop("resolved")
            if resolved and instance.resolved_at is None:
                data["resolved_at"] = conf.now()
            elif not resolved:
                data["resolved_at"] = None
        return super().update(instance, data)


class MessageSerializer(serializers.ModelSerializer):
    chat_title = serializers.CharField(source="chat.title", read_only=True)
    user_name = serializers.CharField(source="user.name", read_only=True, allow_null=True)
    project_name = serializers.CharField(source="project.name", read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = ["id", "chat", "chat_title", "msg_id", "user", "user_name", "date", "text", "kind", "project", "project_name", "source", "items"]
        read_only_fields = fields
