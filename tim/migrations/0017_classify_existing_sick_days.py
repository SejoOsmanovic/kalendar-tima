from django.db import migrations


def classify_sick_days(apps, schema_editor):
    EntryType = apps.get_model("tim", "EntryType")
    Day = apps.get_model("tim", "Day")
    for entry_type in EntryType.objects.all():
        if entry_type.name.strip().casefold() in ("sick day", "sick days"):
            Day.objects.filter(kind="custom", entry_type=entry_type).update(kind="sick")


class Migration(migrations.Migration):
    dependencies = [("tim", "0016_alter_day_kind_alter_leaverequest_kind_and_more")]
    operations = [migrations.RunPython(classify_sick_days, migrations.RunPython.noop)]
