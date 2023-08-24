from django.http import HttpResponse, HttpRequest
from django.template import loader
from django.contrib.auth.models import User

def list_users(request: HttpRequest) -> HttpResponse:
    all_users = User.objects.all()
    context = {
        "users": all_users
    }
    template = loader.get_template("users/users.html")
    return HttpResponse(template.render(context))
    