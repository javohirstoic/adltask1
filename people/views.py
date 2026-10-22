from django.db.models import Count, Q
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import DataViewSet
from core.models import DataVersion
from core.permissions import ADMIN, BOSS, MANAGER, role_of, roles_required

from . import services
from .models import Department, Person
from .serializers import DepartmentSerializer, PersonLiteSerializer, PersonSerializer

NOT_WRITTEN = "Bu xodim hali guruhga yozmagan"


def _person(name: str) -> Person:
    person = services.find(name)
    if person is None:
        raise NotFound(NOT_WRITTEN)
    return person


class DepartmentView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def post(self, request):
        person = _person(request.data.get("name", ""))
        person.department = services.get_department(request.data.get("department"))
        person.save(update_fields=["department"])
        DataVersion.bump()
        return Response({"ok": True})


class RoleView(APIView):
    """Rol berish faqat admin uchun (o'ziga huquq berib yubormaslik uchun)."""
    permission_classes = [roles_required(ADMIN)]

    def post(self, request):
        role = request.data.get("role", "")
        if role not in ("", *Person.Role.values):
            raise ValidationError("Rol: admin, rahbar, menejer yoki bo'sh")
        person = _person(request.data.get("name", ""))
        person.role = role or None
        person.save(update_fields=["role"])
        DataVersion.bump()
        return Response({"ok": True})


class NameView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    """Rahbar xodimning haqiqiy ism-familiyasini yozadi: hamma joyda (panel, Excel, bot) shu ko'rinadi."""

    def post(self, request):
        person = _person(request.data.get("name", ""))
        new = " ".join(str(request.data.get("new_name", "")).split())[:60]
        if len(new) < 2:
            raise ValidationError("Ism-familiyani yozing")
        if Person.objects.filter(name=new).exclude(id=person.id).exists():
            return Response({"detail": "Bu ism boshqa xodimda bor"}, status=409)
        person.name, person.name_locked = new, True
        person.save(update_fields=["name", "name_locked"])
        DataVersion.bump()
        return Response({"ok": True, "name": new})


class LinkView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def get(self, request):
        return Response(services.invite(_person(request.query_params.get("name", ""))))


class LinkResetView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def post(self, request):
        return Response(services.invite(_person(request.data.get("name", "")), reset=True))


class LinksView(APIView):
    permission_classes = [roles_required(ADMIN, BOSS)]

    def get(self, request):
        return Response({"people": services.invites()})


class DepartmentViewSet(DataViewSet):
    resource = "departments"
    queryset = Department.objects.annotate(people_count=Count("people"))
    serializer_class = DepartmentSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "people_count"]
    ordering = ["name"]


class PersonViewSet(DataViewSet):
    resource = "people"
    queryset = Person.objects.select_related("department", "user").annotate(open_tasks=Count("tasks", filter=Q(tasks__status="open")))
    serializer_class = PersonSerializer
    search_fields = ["name", "username"]
    ordering_fields = ["name", "open_tasks", "department__name"]
    ordering = ["name"]
    filter_params = {"department": "department_id", "role": "role"}

    def get_serializer_class(self):
        return PersonLiteSerializer if role_of(self.request.user) == MANAGER else PersonSerializer

    def perform_destroy(self, instance):
        user = instance.user
        if user is not None and user.is_superuser:
            raise ValidationError("Superuser xodimini o'chirib bo'lmaydi")
        if user is not None and user.pk == self.request.user.pk:
            raise ValidationError("O'z akkauntingizni o'chira olmaysiz")
        super().perform_destroy(instance)
        if user is not None:
            user.delete()  # akkaunt xodim bilan birga ketadi, yetim akkaunt qolmasin
