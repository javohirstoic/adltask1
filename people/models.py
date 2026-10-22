from django.conf import settings
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=40, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Person(models.Model):
    """Guruh a'zosi. Ism unikal: panel va Excelda xodim ism bilan ko'rinadi."""
    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)  # @username bilan tilga olingan, hali yozmagan xodimda yo'q
    name = models.CharField(max_length=80, unique=True)
    username = models.CharField(max_length=64, null=True, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="people")
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        BOSS = "rahbar", "Rahbar"
        MANAGER = "menejer", "Loyiha menejeri"

    # Rol ikki joyda ishlaydi: panelda ruxsatlar (core.permissions) va Telegramda (boshqalarga vazifa berish, savollarni hal qilish)
    role = models.CharField(max_length=16, choices=Role.choices, null=True, blank=True)
    # Panelga kirish akkaunti. Akkauntsiz xodim faqat Telegramda ishtirok etadi
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="person")
    invite_token = models.CharField(max_length=32, unique=True, null=True, blank=True)  # t.me/<bot>?start=<token>
    dm_chat_id = models.BigIntegerField(null=True, blank=True)     # xodim botga Start bosgan chat
    dm_linked_at = models.DateTimeField(null=True, blank=True)
    name_locked = models.BooleanField(default=False)               # rahbar yozgan ism Telegram nomi bilan almashmaydi

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people"

    def __str__(self):
        return self.name
