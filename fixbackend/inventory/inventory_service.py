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
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
import asyncio
import logging
from collections import defaultdict
from typing import AsyncIterator, List, Optional, Dict, Set, Tuple

from fixcloudutils.service import Service
from fixcloudutils.types import Json
from pydantic import BaseModel

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.inventory.inventory_client import InventoryClient

log = logging.getLogger(__name__)


class AccountSummary(BaseModel):
    id: str
    name: str
    cloud: str
    failed_by_severity: Dict[str, int]


class BenchmarkSummary(BaseModel):
    id: str
    title: str
    framework: str
    version: str
    clouds: List[str]
    description: str
    nr_of_checks: int
    accounts: List[AccountSummary]


class InventoryService(Service):
    def __init__(self, client: InventoryClient) -> None:
        self.client = client

    async def benchmark(
        self,
        db: GraphDatabaseAccess,
        benchmark_name: str,
        *,
        accounts: Optional[List[str]] = None,
        severity: Optional[str] = None,
        only_failing: bool = False,
    ) -> AsyncIterator[Json]:
        report = f"report benchmark load {benchmark_name}"
        if accounts:
            report += f" --accounts {' '.join(accounts)}"
        if severity:
            report += f" --severity {severity}"
        if only_failing:
            report += " --only-failing"

        return self.client.execute_single(db, report + " | dump")

    async def summary(self, db: GraphDatabaseAccess) -> List[BenchmarkSummary]:
        async def account_summary() -> Tuple[Dict[str, AccountSummary], Dict[str, Set[str]], Dict[str, str]]:
            summaries: Dict[str, AccountSummary] = {}
            check_accounts: Dict[str, Set[str]] = defaultdict(set)
            check_severity: Dict[str, str] = {}

            async for entry in self.client.aggregate(
                db,
                "search /security.has_issues==true | aggregate "
                "/security.issues[].check as check_id,"
                "/security.issues[].severity as severity,"
                "/ancestors.account.reported.id as account_id,"
                "/ancestors.account.reported.name as account_name,"
                "/ancestors.cloud.reported.name as cloud"
                ": sum(1)",
            ):
                group = entry["group"]
                check_id = group["check_id"]
                account_id = group["account_id"]
                account_name = group["account_name"]
                cloud = group["cloud"]
                if account_id is not None and account_id not in summaries:
                    summaries[account_id] = AccountSummary(
                        id=account_id, name=account_name, cloud=cloud, failed_by_severity={}
                    )
                check_accounts[check_id].add(account_id)
                check_severity[check_id] = group["severity"]
            return summaries, check_accounts, check_severity

        async def benchmark_summary() -> Tuple[Dict[str, BenchmarkSummary], Dict[str, List[str]]]:
            summaries: Dict[str, BenchmarkSummary] = {}
            benchmark_checks: Dict[str, List[str]] = {}
            for b in await self.client.benchmarks(db, short=True, with_checks=True):
                summary = BenchmarkSummary(
                    id=b["id"],
                    title=b["title"],
                    framework=b["framework"],
                    version=b["version"],
                    clouds=b["clouds"],
                    description=b["description"],
                    nr_of_checks=len(b["report_checks"]),
                    accounts=[],
                )
                summaries[summary.id] = summary
                benchmark_checks[summary.id] = b["report_checks"]
            return summaries, benchmark_checks

        (benchmarks, checks), (accounts, failed_accounts_by_check_id, severity_by_check_id) = await asyncio.gather(
            benchmark_summary(), account_summary()
        )
        for bid, bench in benchmarks.items():
            failed_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for check in checks.get(bid, []):
                if severity := severity_by_check_id.get(check):
                    for account_id in failed_accounts_by_check_id.get(check, []):
                        failed_counter[account_id][severity] += 1
            for account_id, failed_by_severity in failed_counter.items():
                if template := accounts.get(account_id):
                    bench.accounts.append(template.model_copy(update=dict(failed_by_severity=failed_by_severity)))
        return list(benchmarks.values())
