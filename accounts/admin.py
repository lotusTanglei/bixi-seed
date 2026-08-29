from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "display_name", "contact", "email", "is_active", "is_staff", "date_joined")
    search_fields = ("username", "display_name", "contact", "email")
    list_filter = ("is_active", "is_staff", "is_superuser")
