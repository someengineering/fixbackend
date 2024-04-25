#  Copyright (c) 2023. Some Engineering
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Union

from attrs import frozen
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fixbackend.auth.models import User
from fixbackend.ids import CloudAccountId, WorkspaceId
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace

TemplatesPath = Path(__file__).parent / "templates"
_readable_numbers = {0: "zero", 1: "one", 2: "two", 3: "three"}
_bytes_power = {5: "PB", 4: "TB", 3: "GB", 2: "MB", 1: "KB", 0: "B"}


def _readable_number(number: int) -> str:
    return _readable_numbers.get(number, str(number))


def _with_sign(number: int) -> str:
    return str(number) if number < 0 else ("±0" if number == 0 else f"+{number}")


def _readable_bytes(number: int, *, with_sign: Optional[bool] = None) -> str:
    sign = "-" if number < 0 else ("+" if with_sign and number > 0 else "")
    number = abs(number)
    if number < 1024:
        return f"{sign}{number} B"
    for power, unit in _bytes_power.items():
        pot = 1024**power
        if number >= pot:
            return f"{sign}{number // pot} {unit}"
    return f"{sign}{number} B"


def _pluralize(word: str, count: int) -> str:
    plural = "" if count == 1 else "s"
    return f"{_readable_number(count)} {word}{plural}"


@lru_cache(maxsize=1)
def get_env() -> Environment:
    env = Environment(loader=FileSystemLoader(TemplatesPath), undefined=StrictUndefined)
    env.filters["pluralize"] = _pluralize
    env.filters["readable_number"] = _readable_number
    env.filters["readable_bytes"] = _readable_bytes
    env.filters["with_sign"] = _with_sign
    return env


def render(template_name: str, **kwargs: Any) -> str:
    template = get_env().get_template(template_name)
    result = template.render({"template_name": template_name, "uid": str(uid()), **kwargs})
    return result


@frozen(kw_only=True)
class Signup:
    recipient: str

    def subject(self) -> str:
        return "Welcome to fix!"

    def text(self) -> str:
        return f"Welcome to fix, {self.recipient}!"

    def html(self) -> str:
        return render(
            "signup.html",
            title=self.subject(),
            email=self.recipient,
            visit_our_blog_url="https://fix.security/blog",
            connect_with_fix_on_linkedin_url="https://www.linkedin.com/company/fix/",
            discord_url="https://discord.gg/KQ3JeMbE",
            support_email="support@fix.security",
        )


@frozen(kw_only=True)
class Invite:
    inviter: str
    invitation_link: str
    recipient: str

    def subject(self) -> str:
        return "You've been invited to join Fix!"

    def text(self) -> str:
        text = (
            f"{self.inviter} has invited you to join their workspace. "
            "Please click on the link below to accept the invitation. \n\n"
            f"{self.invitation_link}"
        )
        return text

    def html(self) -> str:
        return render(
            "invite.html",
            title=self.subject(),
            inviter=self.inviter,
            action_url=self.invitation_link,
            email=self.recipient,
            support_email="support@fix.security",
        )


@frozen(kw_only=True)
class VerifyEmail:
    recipient: str
    verification_link: str

    def subject(self) -> str:
        return "Fix: verify your e-mail address"

    def text(self) -> str:
        return f"Hello fellow Fix user, click this link to verify your email. {self.verification_link}"

    def html(self) -> str:
        return render(
            "verify_email.html",
            title=self.subject(),
            email=self.recipient,
            verification_link=self.verification_link,
            support_email="support@fix.security",
        )


@frozen(kw_only=True)
class PasswordReset:
    recipient: str
    password_reset_link: str

    def subject(self) -> str:
        return "Fix: password reset"

    def text(self) -> str:
        return f"You requested a password reset link for your Fix account. Here it is: {self.password_reset_link}"

    def html(self) -> str:
        return render(
            "password_reset.html",
            title=self.subject(),
            email=self.recipient,
            action_link=self.password_reset_link,
            support_email="support@fix.security",
        )


@frozen(kw_only=True)
class SecurityScanFinished:
    def subject(self) -> str:
        return "Fix: Security Scan Finished"

    def text(self) -> str:
        return "Your first security scan is finished! You can now view the results in the Fix console."

    def html(self) -> str:
        return render(
            "security_scan_finished.html",
            title=self.subject(),
            fix_console_url="https://app.fix.security/",
        )


@frozen(kw_only=True)
class AccountDegraded:
    cloud_account_id: CloudAccountId
    account_name: Optional[str]
    tenant_id: WorkspaceId

    def account_info(self) -> str:
        formatted = (
            f"{self.account_name} ({self.cloud_account_id})" if self.account_name else f"{self.cloud_account_id}"
        )
        return formatted

    def subject(self) -> str:
        return f"""Account {self.account_info()} cannot be accessed due to permission issues."""

    def text(self) -> str:
        return f"""We were not able to collect latest resource information for account {self.account_info()}. Please ensure the account exists and that the necessary permissions are granted for access.

Please visit https://app.fix.security/workspace-settings/accounts#{self.tenant_id} for more details."""  # noqa

    def html(self) -> str:
        return render(
            "account_degraded.html",
            message=self,
        )


@frozen(kw_only=True)
class UserJoinedWorkspaceMail:
    user: User
    workspace: Workspace

    def subject(self) -> str:
        return """Welcome to Fix!"""

    def text(self) -> str:
        return render("user_joined_workspace.txt", message=self)

    def html(self) -> str:
        return render("user_joined_workspace.html", message=self, user_id=self.user.id)


@frozen(kw_only=True)
class TrialExpiresSoon:
    days_till_expire: int

    def expires_days(self) -> str:
        day = "days"
        if self.days_till_expire == 1:
            day = "day"

        expires_in = f"{self.days_till_expire} {day}"
        return expires_in

    def subject(self) -> str:
        return f"Fix: Your trial is ending in {self.expires_days()}"

    def text(self) -> str:
        return f"""Your Fix trial is ending in { self.expires_days() }. Don't miss out on the benefits of a subscription.

We noticed you haven't bought a Fix subscription yet.

Easy Steps to get a Fix subscription:

 - Log in to Fix (https://app.fix.security), then navigate to Workspace Settings, and click on the Billing tab.
 - Follow the instructions to add your payment method and subscribe to a plan.


What Happens Next?

If you won't get a subscription, soon after your trial expires your account will downgraded to the Free plan.
Only a single user will be able to log in, and the data we collected about your cloud accounts will no longer be available in Fix.
You will also lose access to the features available in the paid plans.

Here for You

If any step in the process feels unclear,
or if you encounter any bumps along the road, our team is standing by.
Contact us at support@fix.security or ping us on Discord at https://discord.gg/fixsecurity.

Warm regards,
The Fix Team
"""  # noqa

    def html(self) -> str:
        return render(
            "trial_expires.html",
            title=self.subject(),
            period=self.expires_days(),
            visit_our_blog_url="https://fix.security/blog",
            connect_with_fix_on_linkedin_url="https://www.linkedin.com/company/fix/",
            discord_url="https://discord.gg/KQ3JeMbE",
            support_email="support@fix.security",
        )


@frozen(kw_only=True)
class TrialExpired:

    def subject(self) -> str:
        return "Fix: Your trial is over"

    def text(self) -> str:
        return """Your trial period is over, but you can still access your account and data. Please upgrade to continue using Fix.

We noticed you haven't bought a Fix subscription yet.

Easy Steps to get a Fix subscription:

 - Log in to Fix (https://app.fix.security), then navigate to Workspace Settings, and click on the Billing tab.
 - Follow the instructions to add your payment method and subscribe to a plan.


What Happens Next?

Only a single user will be able to log in, and the data collected about your cloud accounts will no longer be available in Fix.
You will also lose access to the features available in the paid plans.

Here for You

If any step in the process feels unclear,
or if you encounter any bumps along the road, our team is standing by.
Contact us at support@fix.security or ping us on Discord at https://discord.gg/fixsecurity.

Warm regards,
The Fix Team
"""  # noqa

    def html(self) -> str:
        return render(
            "trial_expired.html",
            title=self.subject(),
            visit_our_blog_url="https://fix.security/blog",
            connect_with_fix_on_linkedin_url="https://www.linkedin.com/company/fix/",
            discord_url="https://discord.gg/KQ3JeMbE",
            support_email="support@fix.security",
        )


EmailMessage = Union[
    Signup,
    Invite,
    VerifyEmail,
    SecurityScanFinished,
    PasswordReset,
    AccountDegraded,
    UserJoinedWorkspaceMail,
    TrialExpiresSoon,
    TrialExpired,
]
