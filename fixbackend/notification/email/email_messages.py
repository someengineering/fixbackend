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
from typing import Any, Optional, Union, Dict

from attrs import frozen
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fixbackend.auth.models import User
from fixbackend.ids import CloudAccountId, CloudName, CloudNames, WorkspaceId
from fixbackend.utils import uid
from fixbackend.workspaces.models import Workspace

TemplatesPath = Path(__file__).parent / "templates"
_bytes_power: Dict[int, Optional[str]] = {5: "PiB", 4: "TiB", 3: "GiB", 2: "MiB", 1: "KiB", 0: "B"}
_decimal_power: Dict[int, Optional[str]] = {5: "P", 4: "T", 3: "G", 2: "M", 1: "K", 0: None}


def _readable_number(number: int, *, with_sign: Optional[bool] = None) -> str:
    return _readable_unit(1000, _decimal_power, None, number, with_sign)


def _readable_unit(
    base: int,
    base_power: Dict[int, Optional[str]],
    base_unit: Optional[str],
    number: int,
    with_sign: Optional[bool] = None,
) -> str:
    bu = f" {base_unit}" if base_unit else ""
    sign = "-" if number < 0 else ("+" if with_sign and number > 0 else "")
    number = abs(number)
    if number < base:
        return f"{sign}{number}{bu}"
    for power, unit in base_power.items():
        pot = base**power
        if number >= pot:
            pu = f" {unit}" if unit else ""
            return f"{sign}{number // pot}{pu}"
    return f"{sign}{number}{bu}"


def _readable_bytes(number: int, *, with_sign: Optional[bool] = None) -> str:
    return _readable_unit(1024, _bytes_power, "B", number, with_sign)


def _pluralize(word: str, count: int) -> str:
    plural = "" if count == 1 else "s"
    return f"{_readable_number(count)} {word}{plural}"


@lru_cache(maxsize=1)
def get_env() -> Environment:
    env = Environment(loader=FileSystemLoader(TemplatesPath), undefined=StrictUndefined)
    env.filters["pluralize"] = _pluralize
    env.filters["readable_number"] = _readable_number
    env.filters["readable_bytes"] = _readable_bytes
    return env


def render(template_name: str, **kwargs: Any) -> str:
    template = get_env().get_template(template_name)
    result = template.render({"template_name": template_name, "uid": str(uid()), **kwargs})
    return result


@frozen(kw_only=True)
class Signup:
    recipient: str

    def subject(self) -> str:
        return "Welcome to Fix!"

    def text(self) -> str:
        return f"Welcome to Fix, {self.recipient}!"

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
        return "You've been invited to join a Fix workspace"

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
        return "Verify your e-mail address"

    def text(self) -> str:
        return f"Hello! Please click this link to verify your email. {self.verification_link}"

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
        return "Reset your Fix password"

    def text(self) -> str:
        return f"We received a request to reset the password for your Fix account. To set a new password, click this link: {self.password_reset_link}"

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
        return "Security scan complete"

    def text(self) -> str:
        return f"""Your first security scan is complete! You can now view the results in the Fix console.

View in Fix: https://app.fix.security"""  # noqa

    def html(self) -> str:
        return render(
            "security_scan_finished.html",
            title=self.subject(),
            fix_console_url="https://app.fix.security",
        )


@frozen(kw_only=True)
class AccountDegraded:
    cloud: CloudName
    cloud_account_id: CloudAccountId
    account_name: Optional[str]
    tenant_id: WorkspaceId
    workspace_name: str
    cf_stack_deleted: bool

    def cloud_name(self) -> str:
        match self.cloud:
            case CloudNames.AWS:
                return "AWS"
            case CloudNames.GCP:
                return "GCP"
            case CloudNames.Azure:
                return "Azure"
            case _:
                return ""

    def account_info(self) -> str:
        formatted = (
            f"{self.account_name} ({self.cloud_account_id})" if self.account_name else f"{self.cloud_account_id}"
        )
        return formatted

    def subject(self) -> str:
        if self.cloud == CloudNames.AWS and self.cf_stack_deleted:
            return f"""Workspace {self.workspace_name}: CloudFormation Stack for account {self.account_info()} was deleted"""  # noqa
        return (
            f"""Workspace {self.workspace_name}: unable to access {self.cloud_name()} account {self.account_info()}"""
        )

    def text(self) -> str:
        if self.cf_stack_deleted:
            return (
                f"""We noticed that you deleted the AWS CloudFormation Stack for account {self.account_info()} in workspace {self.workspace_name} ({self.tenant_id})."""  # noqa
                "The corresponding resources won't be collected."
            )
        return f"""Fix was not able to collect latest resource information for {self.account_name} account {self.account_info()} in workspace {self.workspace_name} ({self.tenant_id}). Please ensure the account exists and that the necessary access permissions have been granted.

View in Fix: https://app.fix.security/workspace-settings/accounts#{self.tenant_id}"""  # noqa

    def html(self) -> str:
        if self.cf_stack_deleted:
            return render(
                "account_deleted.html",
                message=self,
            )
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
        return f"Your Fix trial ends in {self.expires_days()}"

    def text(self) -> str:
        return f"""We noticed you haven't bought a Fix subscription yet, and your trial is about to expire.


How to subscribe:

 - Log in to Fix (https://app.fix.security), then navigate to Workspace Settings, and click on the Billing tab.
 - Follow the instructions to add your payment method and subscribe to a plan.


What happens next?

If you don't purchase a subscription, your account will downgraded to the Free plan after the trial expires.
Only a single user will be able to log in, and the data we collected about your cloud accounts will no longer be available in Fix.
You will also lose access to features only available in paid plans.


Here for you

If any step in the process feels unclear
or if you encounter any bumps along the road, our team is standing by.
Contact us at support@fix.security or ping us on Discord at https://discord.gg/fixsecurity.


Warm regards,
The Fix Team


Log in to Fix: https://app.fix.security
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
        return "Your Fix trial has ended"

    def text(self) -> str:
        return """We noticed you haven't bought a Fix subscription yet, and your trial has expired. Your account has been downgraded to the Free plan, and you have lost access to the features available in the paid plans.

But don't worry, your account data is still there and you can easily get back on track by subscribing to one of our
plans.


How to subscribe:

 - Log in to Fix (https://app.fix.security), then navigate to Workspace Settings, and click on the Billing tab.
 - Follow the instructions to add your payment method and subscribe to a plan.


What happens next?

Only a single user will be able to log in, and the data we collected about your cloud accounts will no longer be available in Fix.
You will also lose access to features only available in paid plans.


Here for you

If any step in the process feels unclear
or if you encounter any bumps along the road, our team is standing by.
Contact us at support@fix.security or ping us on Discord at https://discord.gg/fixsecurity.


Warm regards,
The Fix Team


Log in to Fix: https://app.fix.security
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
