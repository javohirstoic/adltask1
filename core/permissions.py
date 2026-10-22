"""Rollar va ruxsatlar: bitta joyda. Panel (frontend) ham aynan shu jadvaldan foydalanadi (/api/meta -> me.access).

Rol: superuser -> admin; aks holda akkauntga bog'langan Person.role. Roli yo'q foydalanuvchi panelga kira olmaydi.
Resurs ruxsati harflari: c = yaratish, r = ko'rish, u = o'zgartirish, d = o'chirish.
"""
from rest_framework.permissions import BasePermission

ADMIN, BOSS, MANAGER = "admin", "rahbar", "menejer"
ROLE_LABELS = {ADMIN: "Admin", BOSS: "Rahbar", MANAGER: "Loyiha menejeri"}

ACCESS = {
    ADMIN: {"departments": "crud", "people": "crud", "chats": "crud", "projects": "crud", "tasks": "crud", "blockers": "crud",
            "messages": "rd", "decisions": "r", "alerts": "r", "corrections": "rd"},
    BOSS: {"departments": "r", "people": "r", "chats": "r", "projects": "crud", "tasks": "crud", "blockers": "crud",
           "messages": "r", "decisions": "r", "alerts": "r", "corrections": "r"},
    # Menejer: hamma narsa faqat o'z loyihalari doirasida (qarang: scope_ids)
    MANAGER: {"departments": "r", "people": "r", "chats": "r", "projects": "r", "tasks": "crud", "blockers": "crud", "messages": "r"},
}
ACTION_LETTER = {"list": "r", "retrieve": "r", "create": "c", "update": "u", "partial_update": "u", "destroy": "d"}


def role_of(user) -> str | None:
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    person = getattr(user, "person", None)
    return person.role if person and person.role in ACCESS else None


def person_of(user):
    return getattr(user, "person", None) if user and user.is_authenticated else None


def scope_ids(request) -> set[int] | None:
    """Menejer uchun o'z loyihalari id'lari; admin va rahbar uchun None (cheklov yo'q)."""
    if hasattr(request, "_scope_ids"):
        return request._scope_ids
    ids = None
    if role_of(request.user) == MANAGER:
        ids = set(person_of(request.user).managed_projects.values_list("id", flat=True))
    request._scope_ids = ids
    return ids


class HasRole(BasePermission):
    """Standart: tizimga kirgan va roli bor foydalanuvchi."""
    message = "Sizga panel roli berilmagan"

    def has_permission(self, request, view):
        return role_of(request.user) is not None


def roles_required(*allowed: str):
    """APIView uchun: faqat ko'rsatilgan rollar."""
    class Allowed(BasePermission):
        message = "Bu amal sizning rolingiz uchun ochiq emas"

        def has_permission(self, request, view):
            return role_of(request.user) in allowed
    return Allowed


class ResourceAccess(BasePermission):
    """ViewSet uchun: view.resource va ACCESS jadvali bo'yicha harakat (list/create/update/destroy) ruxsati."""
    message = "Bu amal sizning rolingiz uchun ochiq emas"

    def has_permission(self, request, view):
        role = role_of(request.user)
        if role is None:
            return False
        letters = ACCESS[role].get(view.resource, "")
        letter = ACTION_LETTER.get(getattr(view, "action", None))
        return bool(letters) if letter is None else letter in letters
