from django.db import models


class Embedding(models.Model):
    """Vazifa nomining ma'no vektori (256 float): qidiruv uchun kesh."""
    text = models.CharField(max_length=200, unique=True)
    vec = models.BinaryField()


class Correction(models.Model):
    """Rahbar AI tushunishidagi xatoni tuzatgani: fine-tuning uchun to'plam."""
    message = models.ForeignKey("projects.Message", on_delete=models.CASCADE, related_name="corrections")
    text = models.TextField(blank=True, default="")
    old_kind = models.CharField(max_length=10, null=True, blank=True)
    old_project = models.CharField(max_length=80, null=True, blank=True)
    new_kind = models.CharField(max_length=10)
    new_project = models.CharField(max_length=80, null=True, blank=True)
    created_at = models.DateTimeField()


class DemoQueueItem(models.Model):
    """Namuna guruhlarning bugungi, hali vaqti kelmagan xabarlari."""
    at = models.DateTimeField(db_index=True)
    chat_id = models.BigIntegerField()
    title = models.CharField(max_length=200, blank=True)
    msg_id = models.BigIntegerField()
    user_id = models.BigIntegerField(null=True)  # Telegram id
    user_name = models.CharField(max_length=80, blank=True)
    username = models.CharField(max_length=64, null=True, blank=True)
    text = models.TextField(blank=True, default="")
    reply_to = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["at", "id"]
