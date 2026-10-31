from django.urls import path

from .views import CsrfView, InvitationAcceptView, LoginView, LogoutView, MeView, SwitchOrganizationView


urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("switch-organization/", SwitchOrganizationView.as_view(), name="switch-organization"),
    path("invitations/<str:token>/accept/", InvitationAcceptView.as_view(), name="invitation-accept"),
]
