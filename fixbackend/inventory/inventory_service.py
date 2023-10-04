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

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.inventory.inventory_client import InventoryClient, GraphDatabaseNotAvailable
from fixbackend.inventory.schemas import AccountSummary, ReportSummary, BenchmarkSummary

log = logging.getLogger(__name__)

# alias names for better readability
BenchmarkById = Dict[str, BenchmarkSummary]
ChecksByBenchmarkId = Dict[str, List[str]]
ChecksByAccountId = Dict[str, Set[str]]
SeverityByCheckId = Dict[str, str]


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

    async def summary(self, db: GraphDatabaseAccess) -> ReportSummary:
        async def account_summary() -> Dict[str, AccountSummary]:
            return {
                entry["reported"]["id"]: AccountSummary(
                    id=entry["reported"]["id"],
                    name=entry["reported"]["name"],
                    cloud=entry["ancestors"]["cloud"]["reported"]["name"],
                )
                async for entry in self.client.search_list(db, "is (account)")
            }

        async def check_summary() -> Tuple[ChecksByAccountId, SeverityByCheckId]:
            check_accounts: ChecksByAccountId = defaultdict(set)
            check_severity: Dict[str, str] = {}

            async for entry in self.client.aggregate(
                db,
                "search /security.has_issues==true | aggregate "
                "/security.issues[].check as check_id,"
                "/security.issues[].severity as severity,"
                "/ancestors.account.reported.id as account_id"
                ": sum(1)",
            ):
                group = entry["group"]
                check_id = group["check_id"]
                account_id = group["account_id"]
                check_accounts[check_id].add(account_id)
                check_severity[check_id] = group["severity"]
            return check_accounts, check_severity

        async def benchmark_summary() -> Tuple[BenchmarkById, ChecksByBenchmarkId]:
            summaries: BenchmarkById = {}
            benchmark_checks: ChecksByBenchmarkId = {}
            for b in await self.client.benchmarks(db, short=True, with_checks=True):
                summary = BenchmarkSummary(
                    id=b["id"],
                    title=b["title"],
                    framework=b["framework"],
                    version=b["version"],
                    clouds=b["clouds"],
                    description=b["description"],
                    nr_of_checks=len(b["report_checks"]),
                    failed_checks={},
                )
                summaries[summary.id] = summary
                benchmark_checks[summary.id] = b["report_checks"]
            return summaries, benchmark_checks

        try:
            (
                accounts,
                (benchmarks, checks),
                (failed_accounts_by_check_id, severity_by_check_id),
            ) = await asyncio.gather(account_summary(), benchmark_summary(), check_summary())
            for bid, bench in benchmarks.items():
                failed_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                for check in checks.get(bid, []):
                    if severity := severity_by_check_id.get(check):
                        for account_id in failed_accounts_by_check_id.get(check, []):
                            failed_counter[account_id][severity] += 1
                bench.failed_checks = failed_counter
            return ReportSummary(accounts=list(accounts.values()), benchmarks=list(benchmarks.values()))
        except GraphDatabaseNotAvailable:
            log.warning("Graph database not available yet. Returning empty summary.")
            return ReportSummary(accounts=[], benchmarks=[])
