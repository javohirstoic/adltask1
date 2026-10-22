from datetime import datetime

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from actions.services import recent
from core import conf
from core.models import DataVersion
from core.permissions import MANAGER, role_of, scope_ids

from . import services


def period_params(request) -> dict:
    q = request.query_params
    period, start, end = q.get("period", "week"), q.get("start"), q.get("end")
    if period not in ("day", "week", "month", "custom"):
        raise ValidationError("period: day | week | month | custom")
    if period == "custom":
        try:
            datetime.strptime(start or "", "%Y-%m-%d")
            datetime.strptime(end or "", "%Y-%m-%d")
        except ValueError:
            raise ValidationError("Sana YYYY-MM-DD ko'rinishida bo'lsin")
    return {"period": period, "start": start, "end": end}


def as_of(request) -> datetime:
    try:
        return services.resolve_now(request.query_params.get("asof"))
    except ValueError:
        raise ValidationError("asof: YYYY-MM-DD")


def chat_param(request) -> int | None:
    try:
        return int(request.query_params.get("chat") or 0) or None
    except ValueError:
        raise ValidationError("chat: son bo'lsin")


class SummaryView(APIView):
    def get(self, request):
        now, chat, ids = as_of(request), chat_param(request), scope_ids(request)
        data = services.compute(chat_id=chat, now=now, project_ids=ids, **period_params(request))
        data["feed"] = services.feed(chat, now, project_ids=ids)
        data["version"] = DataVersion.current()
        data["ai"] = conf.ai_enabled()
        if role_of(request.user) == MANAGER:
            # qarorlarni bajarish rahbarning ishi: menejerga tavsiya va jurnal ko'rsatilmaydi
            data["decisions"], data["decision_log"] = [], []
        else:
            data["decision_log"] = recent(6)
        return Response(data)


class ProjectDetailView(APIView):
    def get(self, request, pid):
        ids = scope_ids(request)
        data = None if ids is not None and pid not in ids else services.project_detail(
            pid, now=as_of(request), project_ids=ids, **period_params(request))
        if data is None:
            raise NotFound("Loyiha topilmadi")
        return Response(data)


class PersonDetailView(APIView):
    def get(self, request):
        data = services.person_detail(request.query_params.get("name", ""), chat_id=chat_param(request), now=as_of(request),
                                      project_ids=scope_ids(request), **period_params(request))
        if data is None:
            raise NotFound("Xodim topilmadi")
        return Response(data)
