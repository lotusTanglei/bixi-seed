from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_membership_is_active_auditlog"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="membership",
            options={"ordering": ["user__username"]},
        ),
    ]
