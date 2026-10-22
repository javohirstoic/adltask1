from django.http import HttpResponse
from rest_framework.views import APIView

from analytics import services as analytics
from analytics.views import as_of, chat_param, period_params
from core.permissions import scope_ids

from . import services

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportView(APIView):
    """Har ekran o'z jadvalini bitta toza varaqli alohida faylga chiqaradi."""

    def get(self, request):
        data = analytics.compute(chat_id=chat_param(request), now=as_of(request), project_ids=scope_ids(request), **period_params(request))
        content, name = services.panel_export(request.query_params.get("view", "projects"), data)
        return HttpResponse(content, content_type=XLSX, headers={"Content-Disposition": 'attachment; filename="%s"' % name})
