import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models

from accounts.models import User
from organizations.models import Organization


DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


def _cipher():
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class LLMProviderConfig(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="llm_config")
    provider = models.CharField(max_length=80, default=DEFAULT_PROVIDER)
    base_url = models.URLField(blank=True, default=DEFAULT_BASE_URL)
    model = models.CharField(max_length=160, default=DEFAULT_MODEL)
    api_key_encrypted = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_api_key(self, value):
        self.api_key_encrypted = _cipher().encrypt(value.encode("utf-8")).decode("ascii") if value else ""

    def get_api_key(self):
        if not self.api_key_encrypted:
            return ""
        return _cipher().decrypt(self.api_key_encrypted.encode("ascii")).decode("utf-8")


class Conversation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="ai_conversations")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_conversations")
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Message(models.Model):
    ROLE_CHOICES = [("user", "User"), ("assistant", "Assistant")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class FeatureProposal(models.Model):
    STATUS_CHOICES = [
        ("proposed", "Proposed"),
        ("created", "Created"),
        ("rejected", "Rejected"),
    ]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="feature_proposals")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feature_proposals")
    conversation = models.ForeignKey(
        Conversation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="feature_proposals",
    )
    feature = models.OneToOneField(
        "features.Feature",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="proposal",
    )
    requirement = models.TextField()
    key = models.SlugField(max_length=100)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    manifest = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="proposed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ToolCallProposal(models.Model):
    STATUS_CHOICES = [
        ("proposed", "Proposed"),
        ("confirmed", "Confirmed"),
        ("revoked", "Revoked"),
        ("failed", "Failed"),
    ]
    RISK_CHOICES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tool_call_proposals")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tool_call_proposals")
    tool = models.CharField(max_length=120)
    risk = models.CharField(max_length=20, choices=RISK_CHOICES)
    arguments = models.JSONField(default=dict)
    preview = models.JSONField(default=dict)
    diff = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="proposed")
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
