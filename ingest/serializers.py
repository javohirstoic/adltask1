from rest_framework import serializers

from .models import Correction


class CorrectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Correction
        fields = ["id", "message", "text", "old_kind", "old_project", "new_kind", "new_project", "created_at"]
        read_only_fields = fields
