from django.urls import path

from .views import (
    ChatView,
    ConversationListView,
    ConversationMessagesView,
    FeaturePlanView,
    FeatureProposalConfirmView,
    FeatureProposalRejectView,
    LLMConfigView,
)


urlpatterns = [
    path("config/", LLMConfigView.as_view(), name="llm-config"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path("conversations/<int:conversation_id>/messages/", ConversationMessagesView.as_view(), name="conversation-messages"),
    path("chat/", ChatView.as_view(), name="chat"),
    path("feature-plan/", FeaturePlanView.as_view(), name="feature-plan"),
    path("feature-proposals/<int:proposal_id>/confirm/", FeatureProposalConfirmView.as_view(), name="feature-proposal-confirm"),
    path("feature-proposals/<int:proposal_id>/reject/", FeatureProposalRejectView.as_view(), name="feature-proposal-reject"),
]
