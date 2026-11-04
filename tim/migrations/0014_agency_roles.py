from django.db import migrations


def add_roles(apps, schema_editor):
    roles = apps.get_model("tim", "JobRole").objects.using(schema_editor.connection.alias)
    for name, color in [
        ("Financial Controller", "green"),
        ("Head of Agency Operations", "purple"),
        ("Media Buying Operations", "teal"),
        ("Account Manager", "amber"),
        ("Data Analyst", "blue"),
    ]:
        roles.get_or_create(name__iexact=name, defaults={"name": name, "color": color})


class Migration(migrations.Migration):
    dependencies = [("tim", "0013_reversible_leave_decisions")]
    operations = [migrations.RunPython(add_roles, migrations.RunPython.noop)]
