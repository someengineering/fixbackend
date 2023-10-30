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
from typing import AsyncIterator, List, Optional, Dict, Set, Tuple, Literal, TypeVar, Iterable, Callable, Any, Mapping

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
ChecksByBenchmarkId = Dict[str, List[Dict[str, str]]]  # benchmark_id -> [{id: check_id, severity: medium}, ...]
ChecksByAccountId = Dict[str, Set[str]]
SeverityByCheckId = Dict[str, str]
T = TypeVar("T")
V = TypeVar("V")

ReportSeverityScore: Dict[str, int] = defaultdict(
    lambda: 0, **{"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}  # weights for each severity
)
ReportSeverityPriority: Dict[str, int] = defaultdict(
    lambda: 0, **{n: idx for idx, n in enumerate(["info", "low", "medium", "high", "critical"])}
)


def dict_values_by(d: Mapping[T, Iterable[V]], fn: Callable[[T], Any]) -> Iterable[V]:
    # Sort the dict using the given function and return unique values in the order of the sorted keys
    visited = set()
    for v in (v for _, values in sorted(d.items(), key=lambda x: fn(x[0]), reverse=True) for v in values):
        if v not in visited:
            visited.add(v)
            yield v


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

        return self.client.execute_single(db, report + " | dump")  # type: ignore

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
                assert isinstance(elem, dict), f"Expected Json object but got {elem}"
                severity = elem["group"]["severity"]
                if isinstance(acc_id := elem["group"]["account_id"], str):
                    accounts_by_severity[severity].add(acc_id)
                resource_count_by_severity[severity] += elem["count"]
                resource_count_by_kind[elem["group"]["kind"]] += elem["count"]
            # reduce the count by kind dict to the top 3
            reduced = dict(sorted(resource_count_by_kind.items(), key=lambda item: item[1], reverse=True)[:3])
            # reduce the list of accounts to the top 3
            top_accounts = list(islice(dict_values_by(accounts_by_severity, lambda x: ReportSeverityPriority[x]), 3))
            return VulnerabilitiesChanged(
                since=duration,
                accounts_selection=top_accounts,
                resource_count_by_severity=resource_count_by_severity,
                resource_count_by_kind_selection=reduced,
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
                if isinstance(account_id := group["account_id"], str):
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
            top = list(islice(dict_values_by(checks_by_severity, lambda x: ReportSeverityPriority[x]), num))
            return await self.client.issues(db, check_ids=top)

        def bench_account_score(failing_checks: Dict[str, int], benchmark_checks: Dict[str, int]) -> int:
            # Compute the score of an account with respect to a benchmark
            # Weight failing checks by severity and compute an overall percentage
            missing = sum(ReportSeverityScore[severity] * count for severity, count in failing_checks.items())
            total = sum(ReportSeverityScore[severity] * count for severity, count in benchmark_checks.items())
            return int((max(0, total - missing) * 100) // total)

        def overall_score(accounts: Dict[str, AccountSummary]) -> int:
            # The overall score is the average of all account scores
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
                benchmark_severity_count: Dict[str, int] = defaultdict(int)
                for check_info in checks.get(bid, []):
                    check_id = check_info["id"]
                    benchmark_severity_count[check_info["severity"]] += 1
                    available_checks += 1
                    if severity := severity_by_check_id.get(check_id):
                        severity_counter[severity] += 1
                        for account_id in failed_accounts_by_check_id.get(check_id, []):
                            benchmark_counter[account_id][severity] += 1
                            account_counter[account_id][severity] += 1
                            failed_checks_by_severity[severity].add(check_id)
                for account_id, account in accounts.items():
                    if account.cloud in bench.clouds:
                        failing = benchmark_counter.get(account_id)
                        bench.account_summary[account_id] = BenchmarkAccountSummary(
                            score=bench_account_score(failing or {}, benchmark_severity_count), failed_checks=failing
                        )

            # compute a score for every account by averaging the scores of all benchmark results
            for account_id, failing in account_counter.items():
                scores = [
                    ba.score for b in benchmarks.values() for aid, ba in b.account_summary.items() if aid == account_id
                ]
                accounts[account_id].score = sum(scores) // len(scores) if scores else 100

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
