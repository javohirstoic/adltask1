from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import ReadOnlyDataViewSet
from core.permissions import ADMIN, BOSS, roles_required

from . import services
from .models import Alert, Decision
from .serializers import AlertSerializer, DecisionSerializer


class PreviewView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def post(self, request):
        try:
            return Response(services.preview(request.data.get("action") or {}))
        except (ValueError, KeyError) as e:
            raise ValidationError(str(e))


class ExecuteView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def post(self, request):
        try:
            return Response(services.execute(request.data.get("action") or {}, bool(request.data.get("send", True))))
        except (ValueError, KeyError) as e:
            raise ValidationError(str(e))


class CorrectView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    """Rahbar AI xatosini tuzatadi; tuzatish fine-tuning to'plamiga yoziladi."""

    def post(self, request, mid):
        try:
            return Response(services.correct(mid, request.data.get("kind", ""), request.data.get("project_id")))
        except ValueError as e:
            raise ValidationError(str(e))


class DecisionViewSet(ReadOnlyDataViewSet):
    """Qarorlar jurnali: tarix o'zgartirilmaydi."""
    resource = "decisions"
    queryset = Decision.objects.select_related("chat")
    serializer_class = DecisionSerializer
    search_fields = ["title", "note"]
    ordering_fields = ["created_at", "type"]
    ordering = ["-created_at", "-id"]
    filter_params = {"type": "type", "origin": "origin"}


class AlertViewSet(ReadOnlyDataViewSet):
    """Botning guruhdagi savollari va ularga javoblar."""
    resource = "alerts"
    queryset = Alert.objects.select_related("assignee", "giver")
    serializer_class = AlertSerializer
    search_fields = ["text", "assignee__name"]
    ordering_fields = ["created_at", "kind"]
    ordering = ["-created_at", "-id"]
    filter_params = {"kind": "kind", "assignee": "assignee_id"}
