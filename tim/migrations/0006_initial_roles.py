from django.db import migrations


def create_roles(apps, schema_editor):
    roles = apps.get_model("tim", "JobRole").objects.using(schema_editor.connection.alias)
    roles.bulk_create([roles.model(name="Video Editor", color="purple"),
                       roles.model(name="Media Buyer", color="blue")])


class Migration(migrations.Migration):
    dependencies = [("tim", "0005_jobrole_memberrole")]
    operations = [migrations.RunPython(create_roles, migrations.RunPython.noop)]
