from rest_framework import serializers

from .models import Alert, Decision


class DecisionSerializer(serializers.ModelSerializer):
    chat_title = serializers.CharField(source="chat.title", read_only=True, allow_null=True)

    class Meta:
        model = Decision
        fields = ["id", "created_at", "type", "title", "payload", "chat", "chat_title", "sent", "note", "origin"]
        read_only_fields = fields


class AlertSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source="assignee.name", read_only=True, allow_null=True)
    giver_name = serializers.CharField(source="giver.name", read_only=True, allow_null=True)

    class Meta:
        model = Alert
        fields = ["id", "kind", "created_at", "chat_id", "assignee", "assignee_name", "giver", "giver_name", "task_ids", "options",
                  "text", "resolved_at", "resolution", "resolved_by"]
        read_only_fields = fields
