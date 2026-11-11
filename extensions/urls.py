from django.urls import path

from .views import ExtensionDraftEnableView, ExtensionDraftListView, ExtensionDraftValidateView


urlpatterns = [
    path("drafts/", ExtensionDraftListView.as_view(), name="extension-draft-list"),
    path("drafts/<int:draft_id>/validate/", ExtensionDraftValidateView.as_view(), name="extension-draft-validate"),
    path("drafts/<int:draft_id>/enable/", ExtensionDraftEnableView.as_view(), name="extension-draft-enable"),
]
