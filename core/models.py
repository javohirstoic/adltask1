from django.db import models
from django.db.models import F


class Setting(models.Model):
    """Panelda o'zgartiriladigan sozlama (chegaralar, og'irliklar, brifing vaqtlari)."""
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()

    def __str__(self):
        return "%s = %s" % (self.key, self.value)


class DataVersion(models.Model):
    """Bitta qatorli hisoblagich: har o'zgarishda oshadi, panel shunga qarab o'zini yangilaydi."""
    value = models.PositiveBigIntegerField(default=1)

    @classmethod
    def bump(cls) -> None:
        if not cls.objects.filter(pk=1).update(value=F("value") + 1):
            cls.objects.create(pk=1, value=2)

    @classmethod
    def current(cls) -> int:
        return cls.objects.values_list("value", flat=True).filter(pk=1).first() or 0
