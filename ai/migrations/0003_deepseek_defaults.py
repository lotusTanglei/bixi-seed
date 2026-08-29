from django.db import migrations, models


def upgrade_untouched_configs(apps, schema_editor):
    config_model = apps.get_model("ai", "LLMProviderConfig")
    config_model.objects.filter(
        provider="openai-compatible",
        base_url="",
        model="gpt-4o-mini",
        api_key_encrypted="",
    ).update(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_featureproposal"),
    ]

    operations = [
        migrations.AlterField(
            model_name="llmproviderconfig",
            name="base_url",
            field=models.URLField(blank=True, default="https://api.deepseek.com"),
        ),
        migrations.AlterField(
            model_name="llmproviderconfig",
            name="model",
            field=models.CharField(default="deepseek-chat", max_length=160),
        ),
        migrations.RunPython(upgrade_untouched_configs, migrations.RunPython.noop),
    ]
