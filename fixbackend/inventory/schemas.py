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
from datetime import timedelta
from typing import List, Dict, Optional

from fixcloudutils.types import Json
from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    id: str = Field(description="The account id")
    name: str = Field(description="The account name")
    cloud: str = Field(description="The name of the cloud provider")
    score: int = Field(description="The score of the account", default=100)


class BenchmarkAccountSummary(BaseModel):
    score: int = Field(description="The score of the account", default=0)
    failed_checks: Optional[Dict[str, int]] = Field(description="The number of failed checks by severity.")


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


class VulnerabilitiesChanged(BaseModel):
    since: timedelta = Field(description="The time since the last report.")
    accounts_selection: List[str] = Field(description="A selection of accounts with highest impact.")
    resource_count_by_severity: Dict[str, int] = Field(description="The number of resources by severity.")
    resource_count_by_kind_selection: Dict[str, int] = Field(
        default="A selection of resource kinds with highest impact."
    )


NoVulnerabilitiesChanged = VulnerabilitiesChanged(
    since=timedelta(0), accounts_selection=[], resource_count_by_severity={}, resource_count_by_kind_selection={}
)


class ReportSummary(BaseModel):
    overall_score: int
    check_summary: CheckSummary = Field(description="Overall summary of all available checks.")
    accounts: List[AccountSummary] = Field(description="The accounts in the inventory.")
    benchmarks: List[BenchmarkSummary] = Field(description="The performed benchmarks.")
    changed_vulnerable: VulnerabilitiesChanged = Field(description="Accounts and resources became vulnerable.")
    changed_compliant: VulnerabilitiesChanged = Field(description="Accounts and resources became compliant.")
    top_checks: List[Json] = Field(description="The most relevant report check definitions.")
