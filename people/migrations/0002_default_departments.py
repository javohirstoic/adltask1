from django.db import migrations

DEPARTMENTS = ["AI", "Backend", "Frontend", "Fullstack", "DevOps", "Dizayn", "Test (QA)"]


def create(apps, schema_editor):
    Department = apps.get_model("people", "Department")
    for name in DEPARTMENTS:
        Department.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("people", "0001_initial")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
