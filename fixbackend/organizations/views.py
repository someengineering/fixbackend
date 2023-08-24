from django.http import HttpResponse, HttpRequest
from django.template import loader
from django.contrib.auth.decorators import login_required
from organizations.models import Organization
from django.http import HttpResponseRedirect
from django.shortcuts import render
from .forms import CreateOrganizationForm
from organizations.utils import create_organization




@login_required(login_url='/accounts/login/')
def user_organizations(request: HttpRequest) -> HttpResponse:
    user = request.user
    admin_of = Organization.objects.filter(owner__organization_user__user=user)
    member_of = Organization.objects.filter(users=user)

    context = {
        "admin_of": admin_of,
        "member_of": member_of
    }

    template = loader.get_template("organizations/user_organizations.html")
    return HttpResponse(template.render(context))



@login_required(login_url='/accounts/login/')
def submit_new_organization(request):
    # if this is a POST request we need to process the form data
    if request.method == "POST":
        # create a form instance and populate it with data from the request:
        form = CreateOrganizationForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            org_name = form.cleaned_data["org_name"]
            myorg = create_organization(request.user, org_name) 
            # ...
            # redirect to a new URL:
            return HttpResponseRedirect("user_organizations")

    # if a GET (or any other method) we'll create a blank form
    else:
        form = CreateOrganizationForm()

    return render(request, "organizations/create_organization.html", {"form": form})