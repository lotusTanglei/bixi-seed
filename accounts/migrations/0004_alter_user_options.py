from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_contact"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={"ordering": ["username"]},
        ),
    ]
