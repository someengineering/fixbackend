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

from typing import Any, Union
from attrs import frozen

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from functools import lru_cache


@lru_cache(maxsize=1)
def get_env() -> Environment:
    return Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"))


def render(template_name: str, **kwargs: Any) -> str:
    template = get_env().get_template(template_name)
    result = template.render(**kwargs)
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
            support_email="support@fix.tt",
        )


@frozen(kw_only=True)
class Invite:
    inviter: str
    invitation_link: str
    recipient: str

    def subject(self) -> str:
        return "You've been invited to join FIX!"

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
            support_email="support@fix.tt",
        )


@frozen(kw_only=True)
class VerifyEmail:
    recipient: str
    verification_link: str

    def subject(self) -> str:
        return "FIX: verify your e-mail address"

    def text(self) -> str:
        return f"Hello fellow FIX user, click this link to verify your email. {self.verification_link}"

    def html(self) -> str:
        return render(
            "verify_email.html",
            title=self.subject(),
            email=self.recipient,
            verification_link=self.verification_link,
            support_email="support@fix.tt",
        )


EmailMessage = Union[Signup, Invite, VerifyEmail]
