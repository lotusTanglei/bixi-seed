from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_username_login")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="contact",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
