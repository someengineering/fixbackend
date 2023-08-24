from django.urls import path
from . import views
from fixbackend.organizations.views import user_organizations, submit_new_organization
from fixbackend.users.views import list_users


urlpatterns = [
    path("", views.home, name="home"),
    path("users", list_users, name="list_users"),
    path("user_organizations", user_organizations, name="user_organizations"),
    path("create_new_organization", submit_new_organization, name="create_organization_form"),
]