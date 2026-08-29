from django.urls import path

from .views import SiteLogoView, SiteSettingsView


urlpatterns = [
    path("site-settings/", SiteSettingsView.as_view(), name="site-settings"),
    path("site-settings/logo/", SiteLogoView.as_view(), name="site-logo"),
]
