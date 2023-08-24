from django.urls import path
from . import views
from fixbackend.users.views import list_users


urlpatterns = [
    path("", views.home, name="home"),
    path("users", list_users, name="list_users"),
]