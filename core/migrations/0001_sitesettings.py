from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                ("site_name", models.CharField(default="Bixi Seed", max_length=80)),
                ("logo_path", models.CharField(blank=True, max_length=255)),
                ("logo_content_type", models.CharField(blank=True, max_length=80)),
                ("login_welcome", models.CharField(default="开始构建你的应用", max_length=160)),
                (
                    "login_description",
                    models.CharField(
                        default="登录轻量应用基座，管理组织权限并使用 AI 创建业务功能。",
                        max_length=300,
                    ),
                ),
                ("home_title", models.CharField(default="工作台", max_length=160)),
                ("home_description", models.CharField(default="这里是当前组织的运行概览。", max_length=300)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "站点设置",
                "verbose_name_plural": "站点设置",
            },
        ),
    ]
