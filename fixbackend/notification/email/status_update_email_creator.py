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
import asyncio
import base64
from datetime import timedelta, datetime
from typing import Optional, Tuple, Set

import plotly.graph_objects as go
from fixcloudutils.asyncio.process_pool import AsyncProcessPool
from fixcloudutils.util import utc_str, value_in_path_get, value_in_path

from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.inventory.inventory_service import InventoryService
from fixbackend.inventory.schemas import Scatters
from fixbackend.notification.email.email_messages import render
from fixbackend.workspaces.models import Workspace

color_codes = [
    "#B7B8D3",  # Light Periwinkle
    "#FF9E80",  # Salmon Pink
    "#FFD580",  # Light Gold
    "#74C2BD",  # Soft Turquoise
    "#D3B5E5",  # Light Lavender
    "#B16228",  # Copper
    "#8FBF88",  # Light Moss Green
    "#F47373",  # Soft Red
    "#95DEE3",  # Pale Cyan
    "#6D4C41",  # Coffee Brown
]


def colors(num: int) -> str:
    return color_codes[num % len(color_codes)]


def create_timeline_figure(
    scatters: Scatters,
    *,
    title: Optional[str] = None,
    x_axis: Optional[str] = None,
    y_axis: Optional[str] = None,
    legend_title: Optional[str] = None,
    stacked: bool = False,
) -> str:
    date_fmt = "%d.%m.%y" if scatters.granularity >= timedelta(days=1) else "%d.%m.%y %H:%M"
    x = [at.strftime(date_fmt) for at in scatters.ats]
    fig = go.Figure()
    for idx, scatter in enumerate(scatters.groups):
        color = colors(idx)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=scatter.get_values(scatters.ats),
                mode="lines",
                name=scatter.attributes.get("name") or scatter.group_name,
                stackgroup="one" if stacked else None,
                line=dict(color=color, width=2, shape="spline"),
            )
        )
    fig.update_layout(title=title, xaxis_title=x_axis, yaxis_title=y_axis, legend_title=legend_title)
    return base64.b64encode(fig.to_image(format="png")).decode("utf-8")


def create_gauge_percent(title: str, value: float, previous: float) -> str:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=value,
            number={"font": {"size": 90, "color": "#1C4396", "family": "Arial Black"}},
            title={"text": title, "font": {"color": "#2C3E50", "size": 20}},
            delta={
                "reference": previous,
                "increasing": {"color": "#00AC6B"},
                "decreasing": {"color": "#F78400"},
                "font": {"family": "Arial Black", "size": 30},
            },
            domain={"x": [0, 1], "y": [0, 1]},
            gauge={
                "axis": {"range": [0, 100], "nticks": 3, "showticklabels": False},
                "bar": {"color": "#3d58d3", "thickness": 1},
                "borderwidth": 0,
                "steps": [{"range": [0, 100], "color": "#dfe7fa"}],
            },
        ),
        # layout=go.Layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), # transparent background
    )
    return base64.b64encode(fig.to_image(format="png")).decode("utf-8")


class StatusUpdateEmailCreator:

    def __init__(
        self,
        inventory_service: InventoryService,
        db_access: GraphDatabaseAccessManager,
        process_pool: AsyncProcessPool,
    ):
        self.inventory_service = inventory_service
        self.db_access = db_access
        self.process_pool = process_pool

    async def create_messages(self, workspace: Workspace, now: datetime, duration: timedelta) -> Tuple[str, str, str]:
        dba = await self.db_access.get_database_access(workspace.id)
        assert dba is not None, f"No database access for workspace: {workspace.id}"
        duration_name = "month" if duration.days > 27 else "week"
        start = now - duration

        async with self.inventory_service.client.search(dba, "is(account)") as response:
            account_names = {
                value_in_path(acc, "reported.id"): value_in_path(acc, "reported.name") async for acc in response
            }

        async def progress(
            metric: str, not_exist: int, group: Optional[Set[str]] = None, aggregation: Optional[str] = None
        ) -> Tuple[int, int]:
            async with self.inventory_service.client.timeseries(
                dba, metric, start=now - duration, end=now, granularity=duration, group=group, aggregation=aggregation
            ) as response:
                entries = [int(r["v"]) async for r in response]
                if len(entries) == 0:  # timeseries haven't been created yet
                    return not_exist, 0
                elif len(entries) == 1:  # the timeseries does not exist longer than the current period
                    return entries[0], 0
                else:
                    return entries[1], entries[1] - entries[0]

        async def resources_per_account_timeline() -> Tuple[Scatters, str]:
            scatters = await self.inventory_service.timeseries_scattered(
                dba,
                "resources",
                start=now - duration,
                end=now,
                granularity=timedelta(days=1),
                group={"account_id"},
                aggregation="sum",
            )
            for scatter in scatters.groups:
                acc_id = scatter.group.get("account_id", "<no account name>")
                scatter.attributes["name"] = account_names.get(acc_id, acc_id)
            return scatters, await self.process_pool.submit(
                create_timeline_figure,
                scatters,
                title="Resources per account",
                y_axis="Nr of Resources",
                legend_title="Accounts",
                stacked=True,
            )

        async def nr_of_changes() -> Tuple[int, int, int]:
            cmd = (
                f"history --after {utc_str(start)} --change node_created --change node_updated --change node_deleted | "
                "aggregate /change: sum(1) as count | dump"
            )
            async with self.inventory_service.client.execute_single(dba, cmd) as result:
                changes = {value_in_path(r, "group.change"): value_in_path_get(r, "count", 0) async for r in result}
                return changes.get("node_created", 0), changes.get("node_updated", 0), changes.get("node_deleted", 0)

        async def overall_score() -> Tuple[str, Tuple[int, int]]:
            current, diff = await progress("account_score", 100, group=set(), aggregation="avg")
            image = await self.process_pool.submit(create_gauge_percent, "Security Score", current, current + diff)
            return image, (current, diff)

        (
            (scatters, account_timeline_image),
            (score_image, score_progress),
            resource_changes,
            instances_progress,
            cores_progress,
            memory_progress,
            volumes_progress,
            volume_bytes_progress,
            databases_progress,
            databases_bytes_progress,
        ) = await asyncio.gather(
            resources_per_account_timeline(),
            overall_score(),
            nr_of_changes(),
            progress("instances", 0, group=set(), aggregation="sum"),
            progress("cores_total", 0, group=set(), aggregation="sum"),
            progress("memory_bytes", 0, group=set(), aggregation="sum"),
            progress("volumes_total", 0, group=set(), aggregation="sum"),
            progress("volume_bytes", 0, group=set(), aggregation="sum"),
            progress("databases_total", 0, group=set(), aggregation="sum"),
            progress("databases_bytes", 0, group=set(), aggregation="sum"),
        )
        args = dict(
            workspace_name=workspace.name,
            duration=duration_name,
            accounts=len(scatters.groups),  # type: ignore
            resource_changes=resource_changes,
            account_timeline_image=account_timeline_image,
            score_image=score_image,
            score_progress=score_progress,
            instances_progress=instances_progress,
            cores_progress=cores_progress,
            memory_progress=memory_progress,
            volumes_progress=volumes_progress,
            volume_bytes_progress=volume_bytes_progress,
            databases_progress=databases_progress,
            databases_bytes_progress=databases_bytes_progress,
        )
        subject = render("status-update.subject", **args).strip()
        html = render("status-update.html", **args)
        txt = render("status-update.txt", **args)
        return subject, html, txt
