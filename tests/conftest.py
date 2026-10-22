import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from people.models import Person
from projects.models import Project

PASSWORD = "Parol-12345!"


@pytest.fixture(autouse=True)
def _db(db, settings):
    """Har test o'z tranzaksiyasida ishlaydi; parol xeshi testda tez bo'lsin."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture()
def make_client():
    """make_client("menejer", "Dilshod", projects=[p1]) -> (APIClient, Person): rol, panel akkaunti va o'z loyihalari bilan."""
    def make(role, name, projects=()):
        person = Person.objects.create(name=name, username=name.lower().replace(" ", "_"), role=role)
        user = get_user_model().objects.create_user(person.username, password=PASSWORD)
        person.user = user
        person.save()
        for p in projects:
            Project.objects.filter(id=p.id).update(manager=person)
        client = APIClient()
        assert client.login(username=person.username, password=PASSWORD)
        return client, person
    return make
