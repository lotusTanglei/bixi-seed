from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0004_deepseek_v4_flash_default"),
    ]

    operations = [
        migrations.AlterField(
            model_name="llmproviderconfig",
            name="model",
            field=models.CharField(default="deepseek-v4-flash", max_length=160),
        ),
    ]
