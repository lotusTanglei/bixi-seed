from django.db import models


class SiteSettings(models.Model):
    """单机部署级品牌配置，不承载任何业务数据。"""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    site_name = models.CharField(max_length=80, default="Bixi Seed")
    logo_path = models.CharField(max_length=255, blank=True)
    logo_content_type = models.CharField(max_length=80, blank=True)
    login_welcome = models.CharField(max_length=160, default="开始构建你的应用")
    login_description = models.CharField(
        max_length=300,
        default="登录轻量应用基座，管理组织权限并使用 AI 创建业务功能。",
    )
    home_title = models.CharField(max_length=160, default="工作台")
    home_description = models.CharField(max_length=300, default="这里是当前组织的运行概览。")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "站点设置"
        verbose_name_plural = "站点设置"
