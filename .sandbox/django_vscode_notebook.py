# A script that's needed to use a jupyter notebook instead of a django shell.
# Without this, you won't be able to import django modules
import sys, os, django

# Find the project base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add the project base directory to the sys.path
# This means the script will look in the base directory for any module imports
# Therefore you'll be able to import analysis.models etc
sys.path.insert(0, BASE_DIR)

# The DJANGO_SETTINGS_MODULE has to be set to allow us to access django imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

#  Allow queryset filtering asynchronously when running in a Jupyter notebook
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

# This is for setting up django
django.setup()