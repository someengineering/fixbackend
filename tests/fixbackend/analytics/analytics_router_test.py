#  Copyright (c) 2024. Some Engineering
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
from starlette.testclient import TestClient

from fixbackend.analytics.events import AEEmailOpened
from fixbackend.analytics.router import analytics_router
from fixbackend.dependencies import FixDependencies
from fixbackend.utils import uid
from tests.fixbackend.conftest import InMemoryAnalyticsEventSender


def test_analytics_router(fix_deps: FixDependencies, analytics_event_sender: InMemoryAnalyticsEventSender):
    client = TestClient(analytics_router(fix_deps))
    user_id = uid()
    client.get("/analytics/email_opened/pixel", params={"user": user_id, "email": "foo"})
    client.get("/analytics/email_opened/pixel", params={"user": user_id, "email": "blah"})
    assert len(analytics_event_sender.events) == 2
    for event in analytics_event_sender.events:
        assert isinstance(event, AEEmailOpened)
        assert event.user_id == user_id
        assert event.kind == "fix_email_opened"
        assert event.email in ["foo", "blah"]
