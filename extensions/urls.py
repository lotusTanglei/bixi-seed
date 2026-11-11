from django.urls import path

from .views import ExtensionDraftListView, ExtensionDraftValidateView


urlpatterns = [
    path("drafts/", ExtensionDraftListView.as_view(), name="extension-draft-list"),
    path("drafts/<int:draft_id>/validate/", ExtensionDraftValidateView.as_view(), name="extension-draft-validate"),
]
