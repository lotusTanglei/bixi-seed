import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_alter_membership_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="organizations.organization",
            ),
        ),
    ]
