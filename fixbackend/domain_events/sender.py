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


from abc import ABC, abstractmethod
from fastapi import Depends
from typing import Annotated
from fixbackend.domain_events.events import Event


class DomainEventSender(ABC):
    @abstractmethod
    async def publish(self, event: Event) -> None:
        pass


def get_domain_event_sender() -> DomainEventSender:
    raise NotImplementedError("This component should be injected during setup_teardown_application call in app.py")


DomainEventSenderDependency = Annotated[DomainEventSender, Depends(get_domain_event_sender)]
