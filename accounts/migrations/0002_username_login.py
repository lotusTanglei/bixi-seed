from django.db import migrations, models


def populate_usernames(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.order_by("id"):
        base = (user.email or f"user-{user.pk}").strip().casefold()[:80]
        candidate = base or f"user-{user.pk}"
        suffix = 2
        while User.objects.filter(username=candidate).exclude(pk=user.pk).exists():
            tail = f"-{suffix}"
            candidate = f"{base[:80 - len(tail)]}{tail}"
            suffix += 1
        user.username = candidate
        user.save(update_fields=["username"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=80, null=True),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=80, unique=True),
        ),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True),
        ),
    ]
