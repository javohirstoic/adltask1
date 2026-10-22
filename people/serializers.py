from django.db import transaction
from rest_framework import serializers

from . import services
from .models import Department, Person


class DepartmentSerializer(serializers.ModelSerializer):
    people_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "people_count"]

    def validate_name(self, value):
        return " ".join(value.split())[:40]


class PersonSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, allow_null=True)
    open_tasks = serializers.IntegerField(read_only=True)
    dm_linked = serializers.SerializerMethodField()
    role = serializers.ChoiceField(choices=Person.Role.choices, allow_null=True, allow_blank=True, required=False)
    account = serializers.CharField(source="user.username", read_only=True, allow_null=True)
    # panel akkaunti (faqat admin yozadi): bo'sh qoldirilsa akkaunt o'zgarmaydi
    login = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=150)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})

    class Meta:
        model = Person
        fields = ["id", "telegram_id", "name", "username", "department", "department_name", "role", "dm_linked", "open_tasks",
                  "account", "login", "password"]

    def get_dm_linked(self, obj) -> bool:
        return bool(obj.dm_chat_id)

    def validate_name(self, value):
        value = " ".join(value.split())[:70]
        if len(value) < 2:
            raise serializers.ValidationError("Ism-familiyani yozing")
        return value

    def validate_role(self, value):
        return value or None

    def validate_username(self, value):
        return (value or "").lstrip("@") or None

    def validate(self, data):
        # akkaunt faqat rol bilan ma'noli: rolsiz foydalanuvchi panelga kira olmaydi
        role = data["role"] if "role" in data else (self.instance.role if self.instance else None)
        if (data.get("login") or data.get("password")) and not role:
            raise serializers.ValidationError({"role": "Panel akkaunti uchun rol tanlang"})
        return data

    def _account(self, person, data):
        try:
            services.set_account(person, data.pop("login", None), data.pop("password", None))
        except ValueError as e:
            raise serializers.ValidationError({"login": str(e)})

    @transaction.atomic
    def create(self, data):
        data["name_locked"] = True  # rahbar yozgan ism Telegram nomi bilan almashmaydi
        login, password = data.pop("login", None), data.pop("password", None)
        person = super().create(data)
        self._account(person, {"login": login, "password": password})
        return person

    @transaction.atomic
    def update(self, instance, data):
        if "name" in data and data["name"] != instance.name:
            data["name_locked"] = True
        login, password = data.pop("login", None), data.pop("password", None)
        person = super().update(instance, data)
        self._account(person, {"login": login, "password": password})
        return person


class PersonLiteSerializer(serializers.ModelSerializer):
    """Menejer uchun: vazifa biriktirish uchun yetarli, boshqa loyihalardagi yuklama va aloqa ma'lumoti ko'rinmaydi."""
    department_name = serializers.CharField(source="department.name", read_only=True, allow_null=True)

    class Meta:
        model = Person
        fields = ["id", "name", "username", "department", "department_name"]
        read_only_fields = fields
