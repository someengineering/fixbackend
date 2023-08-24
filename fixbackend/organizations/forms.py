from django import forms


class CreateOrganizationForm(forms.Form):
    org_name = forms.CharField(label="Organization name", max_length=256)