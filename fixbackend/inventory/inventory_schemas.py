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
from datetime import timedelta, datetime
from enum import StrEnum
from typing import List, Dict, Optional, Literal, Tuple, Union, Any
from urllib.parse import urlencode

from fixcloudutils.types import Json
from fixcloudutils.util import utc_str
from pydantic import BaseModel, Field

from fixbackend.ids import WorkspaceId


class AccountSummary(BaseModel):
    id: str = Field(description="The account id")
    name: str = Field(description="The account name")
    cloud: str = Field(description="The name of the cloud provider")
    resource_count: int = Field(description="The number of resources in the account")
    failed_resources_by_severity: Dict[str, int] = Field(description="The number of failed resources by severity.")
    score: int = Field(description="The score of the account", default=100)
    exported_at: Optional[datetime] = Field(description="The time the account was exported.")


class BenchmarkAccountSummary(BaseModel):
    score: int = Field(description="The score of the account", default=0)
    failed_checks: Optional[Dict[str, int]] = Field(description="The unique number of failed checks by severity.")
    failed_resource_checks: Optional[Dict[str, int]] = Field(
        description="The absolite number of failing resources over all checks by severity. "
        "One resource might fail multiple checks."
    )


class BenchmarkSummary(BaseModel):
    id: str = Field(description="The id of the benchmark.")
    title: str = Field(description="The title of the benchmark.")
    framework: str = Field(description="The framework of the benchmark.")
    version: str = Field(description="The version of the benchmark.")
    clouds: List[str] = Field(description="The clouds the benchmark is available for.")
    description: str = Field(description="The description of the benchmark.")
    nr_of_checks: int = Field(description="The number of checks in the benchmark.")
    account_summary: Dict[str, BenchmarkAccountSummary] = Field(
        description="Information of the account with respect to this benchmark.", default_factory=dict
    )


class CheckSummary(BaseModel):
    available_checks: int = Field(description="The number of all available checks.")
    failed_checks: int = Field(description="The number of failed checks.")
    failed_checks_by_severity: Dict[str, int] = Field(description="The number of failed checks by severity.")
    available_resources: int = Field("The number of all available resources.")
    failed_resources: int = Field(description="The number of failed resources.")
    failed_resources_by_severity: Dict[str, int] = Field(description="The number of failed resources by severity.")


class VulnerabilitiesChanged(BaseModel):
    since: timedelta = Field(description="The time since the last report.")
    accounts_selection: List[str] = Field(description="A selection of accounts with highest impact.")
    resource_count_by_severity: Dict[str, int] = Field(description="The number of resources by severity.")
    resource_count_by_kind_selection: Dict[str, int] = Field(
        default="A selection of resource kinds with highest impact."
    )


class Scatter(BaseModel):
    group_name: str
    group: Dict[str, Optional[str]]
    values: Dict[datetime, float]
    attributes: Dict[str, Any] = Field(default_factory=dict)

    def get_values(self, ats: List[datetime]) -> List[float]:
        # Assume 0 if no value is present
        return [self.values.get(at, 0) for at in ats]

    @property
    def avg(self) -> float:
        return sum(self.values.values()) / len(self.values) if self.values else 0


class Scatters(BaseModel):
    start: datetime
    end: datetime
    granularity: timedelta
    ats: List[datetime]
    groups: List[Scatter]


NoVulnerabilitiesChanged = VulnerabilitiesChanged(
    since=timedelta(0), accounts_selection=[], resource_count_by_severity={}, resource_count_by_kind_selection={}
)


class TimeSeries(BaseModel):
    name: str
    start: datetime
    end: datetime
    granularity: timedelta
    data: List[Json]


class ReportSummary(BaseModel):
    overall_score: int
    check_summary: CheckSummary = Field(description="Overall summary of all available checks.")
    accounts: List[AccountSummary] = Field(description="The accounts in the inventory.")
    benchmarks: List[BenchmarkSummary] = Field(description="The performed benchmarks.")
    changed_vulnerable: VulnerabilitiesChanged = Field(description="Accounts and resources became vulnerable.")
    changed_compliant: VulnerabilitiesChanged = Field(description="Accounts and resources became compliant.")
    top_checks: List[Json] = Field(description="The most relevant report check definitions.")
    vulnerable_resources: Optional[TimeSeries] = Field(
        default=None, description="The number of vulnerable resources over time."
    )


class SearchCloudResource(BaseModel):
    id: str
    name: str
    cloud: str


class SearchStartData(BaseModel):
    accounts: List[SearchCloudResource] = Field(description="The available accounts.")
    regions: List[SearchCloudResource] = Field(description="The available regions.")
    kinds: List[SearchCloudResource] = Field(description="The available resource kinds.")
    severity: List[str] = Field(description="Severity values.")


class CompletePathRequest(BaseModel):
    path: Optional[str] = Field(None, description="The path to complete")
    prop: Optional[str] = Field(
        default=None, description="The property to complete. If path is given, this is the last property in the path."
    )
    kinds: Optional[List[str]] = Field(
        default=None, description="The kinds to consider. If not given, all kinds are considered."
    )
    fuzzy: bool = Field(
        default=False, description="If true, fuzzy matching is used. If false, only exact matches are returned."
    )
    limit: int = Field(
        default=20, description="The maximum number of results to return. If not given, all results are returned."
    )
    skip: int = Field(default=0, description="The number of results to skip. If not given, no results are skipped.")


class HistoryChange(StrEnum):
    node_created = "node_created"  # when the resource is created
    node_updated = "node_updated"  # when the resource is updated
    node_deleted = "node_deleted"  # when the resource is deleted
    node_vulnerable = "node_vulnerable"  # when the resource fails one or more security checks (after being compliant)
    node_compliant = "node_compliant"  # when the resource passes all security checks (after being vulnerable)


class HistorySearch(BaseModel):
    before: Optional[datetime] = Field(default=None, description="The time before which to search.")
    after: Optional[datetime] = Field(default=None, description="The time after which to search.")
    # TODO: remove this field once the frontend uses it
    change: Optional[HistoryChange] = Field(default=None, description="The change to search for.")
    changes: List[HistoryChange] = Field(default_factory=list, description="The change to search for.")

    def all_changes(self) -> List[HistoryChange]:
        if self.change:
            result = set(self.changes)
            result.add(self.change)
            return list(result)
        return self.changes


class SortOrder(BaseModel):
    path: str = Field(description="The path to the property to sort by.")
    direction: Literal["asc", "desc"] = Field(description="The sort direction. Only 'asc' and 'desc' are allowed.")


class SearchListGraphRequest(BaseModel):
    query: str = Field(description="The query to execute.")
    with_edges: bool = Field(default=False, description="If the edges should be included.")


class HistoryTimelineRequest(BaseModel):
    query: str = Field(description="The query to execute.")
    before: datetime = Field(default=None, description="The time before which to search.")
    after: datetime = Field(default=None, description="The time after which to search.")
    changes: List[HistoryChange] = Field(default_factory=list, description="The change to search for.")
    granularity: Optional[str] = Field(default=None, description="The granularity of the timeline.")


class SearchRequest(BaseModel):
    query: str = Field(description="The query to execute.")
    history: Optional[HistorySearch] = Field(default=None, description="If the history should be searched.")
    skip: int = Field(default=0, description="The number of results to skip.", ge=0)
    limit: int = Field(default=50, description="The number of results to return.", gt=0, le=1000)
    count: bool = Field(default=False, description="Also compute the total number of results.")
    sort: List[SortOrder] = Field(default_factory=list, description="The sort order.")

    def ui_link(self, base_url: str, workspace_id: WorkspaceId) -> str:
        params = {"q": self.query}
        if self.history:
            if self.history.before:
                params["before"] = utc_str(self.history.before)
            if self.history.after:
                params["after"] = utc_str(self.history.after)
            if changes := self.history.all_changes():
                params["change"] = ",".join(changes)
        if self.skip:
            params["skip"] = str(self.skip)
        if self.limit:
            params["limit"] = str(self.limit)
        return base_url + "/inventory?" + urlencode(params) + f"#{workspace_id}"


class ReportConfig(BaseModel):
    ignore_checks: Optional[List[str]] = Field(default=None, description="List of checks to ignore.")
    ignore_benchmarks: Optional[List[str]] = Field(default=None, description="List of benchmarks to ignore.")
    override_values: Optional[Json] = Field(
        default=None, description="Default values for the report. Will be merged with the values from the config."
    )


class UpdateSecurityIgnore(BaseModel):
    checks: Union[Literal["*"], List[str], None] = Field(
        description="Checks to ignore. Use '*' to ignore all checks. Use null to reset all checks.",
        examples=[["check1", "check2"], "*", None],
    )


class InventorySummaryRead(BaseModel):
    resources_per_account_timeline: Scatters = Field(description="The number of resources per account over time.")
    score_progress: Tuple[int, int]
    resource_changes: Tuple[int, int, int]
    instances_progress: Tuple[int, int]
    cores_progress: Tuple[int, int]
    memory_progress: Tuple[int, int]
    volumes_progress: Tuple[int, int]
    volume_bytes_progress: Tuple[int, int]
    databases_progress: Tuple[int, int]
    databases_bytes_progress: Tuple[int, int]
    buckets_objects_progress: Tuple[int, int]
    buckets_size_bytes_progress: Tuple[int, int]
