from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username=None, password=None, **extra_fields):
        # 保留 email 参数兼容旧脚本，但新账号只需要用户名。
        if username is None:
            username = extra_fields.pop("email", None)
        username = str(username or "").strip().casefold()
        if not username:
            raise ValueError("username is required")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("superuser must have is_superuser=True")
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=80, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    contact = models.CharField(max_length=120, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.display_name or self.username
