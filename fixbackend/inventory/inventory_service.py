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
from datetime import timedelta
from itertools import islice
from typing import AsyncIterator, List, Optional, Dict, Set, Tuple, Literal

from fixcloudutils.service import Service
from fixcloudutils.types import Json

from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.inventory.inventory_client import InventoryClient, GraphDatabaseNotAvailable
from fixbackend.inventory.schemas import (
    AccountSummary,
    ReportSummary,
    BenchmarkSummary,
    VulnerabilitiesChanged,
    NoVulnerabilitiesChanged,
    BenchmarkAccountSummary,
    CheckSummary,
)

log = logging.getLogger(__name__)

# alias names for better readability
BenchmarkById = Dict[str, BenchmarkSummary]
ChecksByBenchmarkId = Dict[str, List[str]]
ChecksByAccountId = Dict[str, Set[str]]
SeverityByCheckId = Dict[str, str]


ReportSeverityScore: Dict[str, int] = defaultdict(
    lambda: 0, **{"info": 0, "low": 7, "medium": 13, "high": 27, "critical": 53}  # the sum is 100
)
ReportSeverityPriority: Dict[str, int] = defaultdict(
    lambda: 0, **{n: idx for idx, n in enumerate(["info", "low", "medium", "high", "critical"])}
)


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
        async def issues_since(
            duration: timedelta, change: Literal["node_vulnerable", "node_compliant"]
        ) -> VulnerabilitiesChanged:
            accounts_by_severity: Dict[str, Set[str]] = defaultdict(set)
            resource_count_by_severity: Dict[str, int] = defaultdict(int)
            resource_count_by_kind: Dict[str, int] = defaultdict(int)
            async for elem in self.client.execute_single(
                db,
                f"history --change {change} --after {duration.total_seconds()}s | aggregate "
                f"/ancestors.account.reported.id as account_id, "
                f"/security.severity as severity,"
                f"kind as kind"
                ": count(name) as count",
            ):
                severity = elem["group"]["severity"]
                accounts_by_severity[severity].add(elem["group"]["account_id"])
                resource_count_by_severity[severity] += elem["count"]
                resource_count_by_kind[elem["group"]["kind"]] += elem["count"]
            return VulnerabilitiesChanged(
                since=duration,
                accounts_by_severity=accounts_by_severity,
                resource_count_by_severity=resource_count_by_severity,
                resource_count_by_kind=resource_count_by_kind,
            )

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
                )
                summaries[summary.id] = summary
                benchmark_checks[summary.id] = b["report_checks"]
            return summaries, benchmark_checks

        async def top_issues(checks_by_severity: Dict[str, Set[str]], num: int) -> List[Json]:
            list_gen = sorted(checks_by_severity.items(), key=lambda x: ReportSeverityPriority[x[0]], reverse=True)
            top = list(islice((id for _, check_ids in list_gen for id in check_ids), num))
            return await self.client.issues(db, check_ids=top)

        def account_score(failing_checks: Dict[str, int]) -> int:
            # for the moment we ignore the count of failing checks and only look at the severity
            return max(0, 100 - sum(ReportSeverityScore[severity] for severity in failing_checks.keys()))

        def overall_score(accounts: Dict[str, AccountSummary]) -> int:
            total_score = sum(account.score for account in accounts.values())
            total_accounts = len(accounts)
            return total_score // total_accounts if total_accounts > 0 else 100

        default_time_since = timedelta(days=7)

        try:
            (
                accounts,
                (benchmarks, checks),
                (failed_accounts_by_check_id, severity_by_check_id),
                vulnerable_changed,
                compliant_changed,
            ) = await asyncio.gather(
                account_summary(),
                benchmark_summary(),
                check_summary(),
                issues_since(default_time_since, "node_vulnerable"),
                issues_since(default_time_since, "node_compliant"),
            )

            # combine benchmark and account data
            account_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            severity_counter: Dict[str, int] = defaultdict(int)
            failed_checks_by_severity: Dict[str, Set[str]] = defaultdict(set)
            available_checks = 0
            for bid, bench in benchmarks.items():
                benchmark_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                for check in checks.get(bid, []):
                    available_checks += 1
                    if severity := severity_by_check_id.get(check):
                        severity_counter[severity] += 1
                        for account_id in failed_accounts_by_check_id.get(check, []):
                            benchmark_counter[account_id][severity] += 1
                            account_counter[account_id][severity] += 1
                            failed_checks_by_severity[severity].add(check)
                for account_id, account in accounts.items():
                    if account.cloud in bench.clouds:
                        failing = benchmark_counter.get(account_id)
                        bench.account_summary[account_id] = BenchmarkAccountSummary(
                            score=account_score(failing) if failing else 100, failed_checks=failing
                        )

            # compute a score for every account
            for account_id, failing in account_counter.items():
                accounts[account_id].score = account_score(failing)

            # get issues for the top 5 issue_ids
            tops = await top_issues(failed_checks_by_severity, num=5)

            return ReportSummary(
                check_summary=CheckSummary(
                    available_checks=available_checks,
                    failed_checks=sum(v for v in severity_counter.values()),
                    failed_checks_by_severity=severity_counter,
                ),
                overall_score=overall_score(accounts),
                accounts=list(accounts.values()),
                benchmarks=list(benchmarks.values()),
                changed_vulnerable=vulnerable_changed,
                changed_compliant=compliant_changed,
                top_checks=tops,
            )

        except GraphDatabaseNotAvailable:
            log.warning("Graph database not available yet. Returning empty summary.")
            return ReportSummary(
                check_summary=CheckSummary(available_checks=0, failed_checks=0, failed_checks_by_severity={}),
                overall_score=0,
                accounts=[],
                benchmarks=[],
                changed_vulnerable=NoVulnerabilitiesChanged,
                changed_compliant=NoVulnerabilitiesChanged,
                top_checks=[],
            )
