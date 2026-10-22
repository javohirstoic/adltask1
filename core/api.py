"""CRUD uchun umumiy asos: sahifalash, qidiruv, filtr va har o'zgarishda panel versiyasini oshirish."""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import filters, mixins, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination

from .models import DataVersion
from .permissions import ResourceAccess, scope_ids


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 1000


class BumpVersionMixin:
    """Yaratish, o'zgartirish va o'chirishdan keyin panel o'zini yangilasin."""

    def perform_create(self, serializer):
        super().perform_create(serializer)
        DataVersion.bump()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        DataVersion.bump()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        DataVersion.bump()


class QueryFilterMixin:
    """?project=3&status=open kabi oddiy filtrlar: filter_params = {"so'rov nomi": "ORM lookup"}."""
    filter_params: dict = {}

    def get_queryset(self):
        qs = super().get_queryset()
        for param, lookup in self.filter_params.items():
            value = self.request.query_params.get(param)
            if value in (None, ""):
                continue
            try:
                qs = qs.filter(**{lookup: value})
            except (ValueError, TypeError, DjangoValidationError):
                raise ValidationError({param: "Noto'g'ri qiymat"})
        return qs


class ScopeMixin:
    """Menejerga faqat o'z loyihalariga tegishli yozuvlar ko'rinadi. scope_lookup — loyiha id'siga olib boradigan ORM yo'li
    ("project_id", "id"); murakkab holatda scope_queryset(qs, ids) qayta yoziladi."""
    scope_lookup: str | None = None

    def scope_queryset(self, qs, ids):
        return qs.filter(**{self.scope_lookup + "__in": ids}) if self.scope_lookup else qs

    def get_queryset(self):
        qs = super().get_queryset()
        ids = scope_ids(self.request)
        return qs if ids is None else self.scope_queryset(qs, ids)


class _Base(ScopeMixin, QueryFilterMixin):
    """resource — ruxsat jadvali (core.permissions.ACCESS) dagi nom."""
    resource: str = ""
    permission_classes = [ResourceAccess]
    pagination_class = Pagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]


class DataViewSet(BumpVersionMixin, _Base, viewsets.ModelViewSet):
    """To'liq CRUD."""


class ReadOnlyDataViewSet(_Base, viewsets.ReadOnlyModelViewSet):
    """Faqat ko'rish (tizim o'zi yozadigan jadvallar)."""


class DeletableDataViewSet(BumpVersionMixin, mixins.DestroyModelMixin, ReadOnlyDataViewSet):
    """Ko'rish va o'chirish (xabar, tuzatish: tahrirlansa tarix buziladi)."""
