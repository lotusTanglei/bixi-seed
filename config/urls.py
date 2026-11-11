from pathlib import Path

from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from core.views import health


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/", include("core.urls")),
    path("api/auth/", include("accounts.urls")),
    path("api/organizations/", include("organizations.urls")),
    path("api/ai/", include("ai.urls")),
    path("api/features/", include("features.urls")),
    path("api/extensions/", include("extensions.urls")),
]


frontend_index = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
if frontend_index.exists():
    urlpatterns.append(
        re_path(
            r"^(?!api/|admin/|static/).*$",
            TemplateView.as_view(template_name="index.html"),
            name="frontend",
        )
    )
