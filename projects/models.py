from django.db import models


class Chat(models.Model):
    id = models.BigIntegerField(primary_key=True)  # Telegram chat id
    title = models.CharField(max_length=200, blank=True)
    demo = models.BooleanField(default=False)      # namuna ma'lumot
    added_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title or str(self.id)


class Project(models.Model):
    key = models.CharField(max_length=80, unique=True)  # #teg kichik harfda: "hujjataylanishi"
    name = models.CharField(max_length=200)
    aliases = models.CharField(max_length=300, blank=True, default="")  # erkin matnda tanish uchun boshqa nomlar
    chat = models.ForeignKey(Chat, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    # Loyiha menejeri faqat o'z loyihalarini ko'radi va boshqaradi
    manager = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_projects")

    def __str__(self):
        return self.name


class Message(models.Model):
    class Kind(models.TextChoices):
        TASK = "task"
        DONE = "done"
        BLOCKER = "blocker"
        DEADLINE = "deadline"
        REASSIGN = "reassign"
        NONE = "none"

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    msg_id = models.BigIntegerField()
    user = models.ForeignKey("people.Person", null=True, on_delete=models.SET_NULL, related_name="messages")
    date = models.DateTimeField()  # Toshkent vaqti
    text = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NONE)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    source = models.CharField(max_length=10, default="format")  # format | ai | taxmin | tuzatildi
    reply_to = models.BigIntegerField(null=True, blank=True)    # javob berilgan xabarning Telegram id si
    items = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["chat", "msg_id"], name="ux_message_chat_msg")]
        indexes = [models.Index(fields=["date"]), models.Index(fields=["project", "date"])]


class Task(models.Model):
    class Status(models.TextChoices):
        OPEN = "open"
        DONE = "done"
        PROPOSED = "taklif"  # xodim hali qabul qilmagan

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    assignee = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField()
    done_at = models.DateTimeField(null=True, blank=True)
    created_msg = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_tasks")
    done_msg = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="closed_tasks")
    deadline = models.DateField(null=True, blank=True)  # vazifaning o'z muddati

    class Meta:
        indexes = [models.Index(fields=["project", "status"]), models.Index(fields=["created_at"]), models.Index(fields=["done_at"])]


class Blocker(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="blockers")
    text = models.TextField()
    author = models.ForeignKey("people.Person", null=True, blank=True, on_delete=models.SET_NULL, related_name="blockers")
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    msg = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="blockers")
    resolved_msg = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_blockers")
