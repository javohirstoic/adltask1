"""Xodimlar bilan ishlash: ism, shaxsiy havola, rol va panel akkaunti."""
import secrets
import re

from django.conf import settings
from django.db import transaction

from core.models import DataVersion

from .models import Department, Person

NAME_JUNK_RE = re.compile(r"[^\w\s'ʻ’‘`.-]", re.U)
DEMO_TELEGRAM_IDS = (900000000, 900999999)  # namuna xodimlar shu oraliqda


def clean_name(name: str | None) -> str:
    """Telegram nomidagi bezaklarsiz ism: 'Javohir ⚜️' -> 'Javohir'."""
    s = re.sub(r"\s+", " ", NAME_JUNK_RE.sub("", name or "")).strip(" .-")
    return s or (name or "").strip() or "Noma'lum"


def unique_name(base: str, exclude_id: int | None = None, username: str | None = None) -> str:
    """Ism unikal bo'lishi kerak: band bo'lsa @username yoki raqam qo'shiladi."""
    base = base[:70]
    taken = Person.objects.exclude(id=exclude_id) if exclude_id else Person.objects.all()
    candidates = [base] + (["%s (@%s)" % (base, username)] if username else [])
    for c in candidates:
        if not taken.filter(name=c).exists():
            return c
    n = 2
    while taken.filter(name="%s (%d)" % (base, n)).exists():
        n += 1
    return "%s (%d)" % (base, n)


def departments() -> list[str]:
    return list(Department.objects.values_list("name", flat=True))


def get_department(name: str | None) -> Department | None:
    name = (name or "").strip()[:40]
    return Department.objects.get_or_create(name=name)[0] if name else None


def is_lead(telegram_id: int) -> bool:
    if settings.OWNER_ID and telegram_id == settings.OWNER_ID:
        return True
    # admin, rahbar va loyiha menejeri Telegramda ham boshqalarga vazifa bera oladi va botning savollarini hal qiladi
    return Person.objects.filter(telegram_id=telegram_id, role__in=Person.Role.values).exists()


def find(name: str) -> Person | None:
    return Person.objects.filter(name=name).first()


@transaction.atomic
def invite(person: Person, reset: bool = False) -> dict:
    """Xodimning shaxsiy havolasi. Bir marta yaratiladi; reset=True eskisini bekor qiladi."""
    if reset or not person.invite_token:
        person.invite_token = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")
        if reset:
            person.dm_chat_id = person.dm_linked_at = None
        person.save(update_fields=["invite_token", "dm_chat_id", "dm_linked_at"])
        DataVersion.bump()
    linked = bool(person.dm_chat_id) and not reset
    return {"name": person.name, "link": "https://t.me/%s?start=%s" % (settings.BOT_USERNAME, person.invite_token),
            "linked": linked, "linked_at": person.dm_linked_at.strftime("%Y-%m-%d %H:%M:%S") if linked and person.dm_linked_at else None}


def invites() -> list[dict]:
    lo, hi = DEMO_TELEGRAM_IDS
    real = Person.objects.exclude(telegram_id__range=(lo, hi)).order_by("name")
    return [invite(p) for p in real]


def set_account(person: Person, login: str | None, password: str | None) -> None:
    """Xodimga panel akkaunti: yo'q bo'lsa yaratadi, bor bo'lsa login/parolni yangilaydi. Xatolik ValueError."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    User = get_user_model()
    login = (login or "").strip()
    if not login and not password:
        return
    user = person.user
    if user is not None and user.is_superuser:
        raise ValueError("Superuser akkauntini bu yerdan o'zgartirib bo'lmaydi")
    if user is None:
        if not login or not password:
            raise ValueError("Akkaunt uchun login va parol ikkalasi kerak")
        if User.objects.filter(username=login).exists():
            raise ValueError("Bu login band")
        user = User(username=login)
    elif login and login != user.username:
        if User.objects.filter(username=login).exclude(pk=user.pk).exists():
            raise ValueError("Bu login band")
        user.username = login
    if password:
        try:
            validate_password(password, user)
        except DjangoValidationError as e:
            raise ValueError("Parol qabul qilinmadi: " + " ".join(e.messages))
        user.set_password(password)
    user.save()
    if person.user_id != user.pk:
        person.user = user
        person.save(update_fields=["user"])
