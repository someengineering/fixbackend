from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.template import loader

def home(request: HttpRequest) -> HttpResponse:
    template = loader.get_template("home.html")
    context = {
        "user": request.user
    }
    return HttpResponse(template.render(context))
