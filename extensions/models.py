from django.conf import settings
from django.db import models

from organizations.models import Organization


class ExtensionDraft(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("validated", "Validated"), ("rejected", "Rejected"), ("enabled", "Enabled in catalog")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="extension_drafts")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    key = models.SlugField(max_length=100)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    files = models.JSONField(default=dict)
    dependencies = models.JSONField(default=list)
    permission_manifest = models.JSONField(default=list)
    static_checks = models.JSONField(default=dict)
    validated_hash = models.CharField(max_length=64, blank=True)
    enabled_hash = models.CharField(max_length=64, blank=True)
    enabled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="enabled_extension_drafts")
    enabled_at = models.DateTimeField(null=True, blank=True)
    isolation_status = models.CharField(max_length=20, default="not_executed")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "key"], name="unique_extension_draft_key_per_org")
        ]
