import json
from datetime import datetime

from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import DeletableDataViewSet
from core.permissions import ADMIN, roles_required

from .models import Correction
from .serializers import CorrectionSerializer
from .services import Incoming, ingest

MAX_BYTES = 30 * 1024 * 1024


def _export_text(value) -> str:
    if isinstance(value, str):
        return value
    return "".join(part if isinstance(part, str) else part.get("text", "") for part in value or [])


class ImportView(APIView):
    """Telegram Desktop -> Export chat history -> JSON (result.json). Bot qo'shilmasdan oldingi tarix uchun."""
    parser_classes = [MultiPartParser]
    permission_classes = [roles_required(ADMIN)]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError("Fayl yuboring")
        if upload.size > MAX_BYTES:
            return Response({"detail": "Fayl 30 MB dan katta"}, status=413)
        try:
            data = json.loads(upload.read())
            messages = data["messages"]
        except (ValueError, KeyError, TypeError):
            raise ValidationError("Bu Telegram eksport fayli emas (result.json kerak)")
        cid = int(data.get("id") or 0)
        kind = str(data.get("type", ""))
        chat_id = -int("100%d" % cid) if ("supergroup" in kind or "channel" in kind) else -cid
        title = data.get("name") or "Import qilingan guruh"
        added = skipped = 0
        for m in messages:
            if m.get("type") != "message":
                continue
            text = _export_text(m.get("text"))
            if not text.strip():
                continue
            uid = int("".join(ch for ch in str(m.get("from_id") or "") if ch.isdigit()) or 0)
            inc = Incoming(chat_id, title, int(m["id"]), uid, m.get("from") or "Noma'lum", None,
                           datetime.fromisoformat(m["date"]).replace(tzinfo=None), text, m.get("reply_to_message_id"))
            if ingest(inc, use_ai=False).duplicate:
                skipped += 1
            else:
                added += 1
        return Response({"chat": title, "added": added, "skipped": skipped})


class CorrectionViewSet(DeletableDataViewSet):
    """Rahbar tuzatgan AI xatolari (o'qitish to'plami): ko'rish va keraksizini o'chirish."""
    resource = "corrections"
    queryset = Correction.objects.all()
    serializer_class = CorrectionSerializer
    search_fields = ["text", "old_project", "new_project"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at", "-id"]
    filter_params = {"new_kind": "new_kind", "old_kind": "old_kind"}
