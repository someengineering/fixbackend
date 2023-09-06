# The list of all models in the project
# This is used by alembic to generate migrations
#
# If you add a new model, you need to add it here,
# otherwise alembic won't be able to detect it

from fixbackend.auth.models import User, OAuthAccount  # noqa
from fixbackend.organizations.models import Organization, OrganizationInvite  # noqa
