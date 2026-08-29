from django.db import migrations


def replace_old_deepseek_default(apps, schema_editor):
    config_model = apps.get_model("ai", "LLMProviderConfig")
    config_model.objects.filter(
        provider="openai-compatible",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    ).update(model="deepseek-v4-flash")


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0003_deepseek_defaults"),
    ]

    operations = [
        migrations.RunPython(replace_old_deepseek_default, migrations.RunPython.noop),
    ]
