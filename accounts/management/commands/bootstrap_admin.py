import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from organizations.models import Permission
from organizations.services import DEFAULT_PERMISSIONS, create_organization


class Command(BaseCommand):
    help = "创建或更新第一个管理员和组织。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.getenv("BIXI_ADMIN_USERNAME") or os.getenv("BIXI_ADMIN_EMAIL"),
            help="管理员账号；--email 仅作为旧参数兼容",
        )
        parser.add_argument("--email", default=os.getenv("BIXI_ADMIN_EMAIL"), help="可选的联系邮箱")
        parser.add_argument("--contact", default=os.getenv("BIXI_ADMIN_CONTACT"), help="管理员联系方式")
        parser.add_argument("--password", default=os.getenv("BIXI_ADMIN_PASSWORD"))
        parser.add_argument("--organization", default=os.getenv("BIXI_ORGANIZATION_NAME", "我的组织"))
        parser.add_argument("--display-name", default=os.getenv("BIXI_ADMIN_DISPLAY_NAME", "管理员"))

    def handle(self, *args, **options):
        username = (options["username"] or options["email"] or "").strip().casefold()
        contact = (options["contact"] or options["email"] or "").strip()
        password = options["password"] or ""
        organization_name = (options["organization"] or "").strip()
        if not username or not password or not organization_name:
            raise CommandError("username、password 和 organization 都不能为空")
        if len(password) < 10:
            raise CommandError("管理员密码至少需要 10 个字符")

        for code, name, description in DEFAULT_PERMISSIONS:
            Permission.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": description},
            )

        existing_user = User.objects.filter(username=username).first()
        if existing_user is None and not contact:
            raise CommandError("新管理员必须填写联系方式，例如手机号或微信号")
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "display_name": options["display_name"],
                "contact": contact,
                "email": options["email"] or None,
            },
        )
        if created:
            user.set_password(password)
        else:
            user.display_name = options["display_name"] or user.display_name
            user.set_password(password)
            if options["email"]:
                user.email = options["email"]
            if contact:
                user.contact = contact
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()

        if not user.memberships.exists():
            create_organization(user=user, name=organization_name)

        self.stdout.write(self.style.SUCCESS(f"管理员已准备: {user.username}"))
