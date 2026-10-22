from django.db import models


class Decision(models.Model):
    """Rahbar qarorlari jurnali (paneldan yoki guruhda botning savoliga javob)."""
    created_at = models.DateTimeField()
    type = models.CharField(max_length=20)  # reassign | deadline | ping_person | ping_project | ping_blocker | keep
    title = models.CharField(max_length=300, blank=True)
    payload = models.JSONField(null=True, blank=True)
    chat = models.ForeignKey("projects.Chat", null=True, blank=True, on_delete=models.SET_NULL)
    sent = models.BooleanField(default=False)  # Telegramga yuborildimi
    note = models.CharField(max_length=300, blank=True)
    origin = models.CharField(max_length=10, default="panel")  # panel | guruh

    class Meta:
        ordering = ["-id"]


class Alert(models.Model):
    """Botning guruhdagi savoli: yuklama ogohlantirishi yoki vazifa taklifi."""
    class Kind(models.TextChoices):
        LOAD = "yuklama"
        PROPOSAL = "taklif"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    created_at = models.DateTimeField()
    chat_id = models.BigIntegerField(null=True)      # Telegram chat
    msg_id = models.BigIntegerField(null=True)       # vazifa yozilgan xabar
    bot_chat_id = models.BigIntegerField(null=True, blank=True)
    bot_msg_id = models.BigIntegerField(null=True, blank=True)
    giver = models.ForeignKey("people.Person", null=True, on_delete=models.SET_NULL, related_name="given_alerts")
    assignee = models.ForeignKey("people.Person", null=True, on_delete=models.SET_NULL, related_name="alerts")
    task_ids = models.JSONField(default=list)
    options = models.JSONField(default=list)        # tavsiya qilingan xodimlar nomi
    text = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=40, null=True, blank=True)
    resolved_by = models.CharField(max_length=120, null=True, blank=True)
