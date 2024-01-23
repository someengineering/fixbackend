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
import json
import logging
from collections import defaultdict
from datetime import timedelta
from itertools import islice
from typing import List, Optional, Dict, Set, Tuple, Literal, TypeVar, Iterable, Callable, Any, Mapping

from fixcloudutils.asyncio.timed import timed
from fixcloudutils.redis.cache import RedisCache
from fixcloudutils.service import Service
from fixcloudutils.types import Json, JsonElement
from fixcloudutils.util import value_in_path, utc_str, utc
from redis.asyncio import Redis

from fixbackend.domain_events.events import (
    AwsAccountDeleted,
    TenantAccountsCollected,
    CloudAccountNameChanged,
    WorkspaceCreated,
)
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import CloudNames, WorkspaceId
from fixbackend.ids import NodeId
from fixbackend.inventory.inventory_client import InventoryClient, AsyncIteratorWithContext, InventoryException
from fixbackend.inventory.schemas import (
    AccountSummary,
    ReportSummary,
    BenchmarkSummary,
    VulnerabilitiesChanged,
    NoVulnerabilitiesChanged,
    BenchmarkAccountSummary,
    CheckSummary,
    SearchStartData,
    SearchCloudResource,
    SearchRequest,
    TimeSeries,
    ReportConfig,
)
from fixbackend.logging_context import set_cloud_account_id, set_fix_cloud_account_id, set_workspace_id

log = logging.getLogger(__name__)

# alias names for better readability
BenchmarkById = Dict[str, BenchmarkSummary]
ChecksByBenchmarkId = Dict[str, List[Dict[str, str]]]  # benchmark_id -> [{id: check_id, severity: medium}, ...]
ChecksByAccountId = Dict[str, Dict[str, int]]  # account_id -> check_id -> count
SeverityByCheckId = Dict[str, str]
T = TypeVar("T")
V = TypeVar("V")

ReportSeverityList = ["info", "low", "medium", "high", "critical"]
ReportSeverityScore: Dict[str, int] = defaultdict(
    lambda: 0, **{"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}  # weights for each severity
)
ReportSeverityPriority: Dict[str, int] = defaultdict(lambda: 0, **{n: idx for idx, n in enumerate(ReportSeverityList)})
Inventory = "inventory-service"


def dict_values_by(d: Mapping[T, Iterable[V]], fn: Callable[[T], Any]) -> Iterable[V]:
    # Sort the dict using the given function and return unique values in the order of the sorted keys
    visited = set()
    for v in (v for _, values in sorted(d.items(), key=lambda x: fn(x[0]), reverse=True) for v in values):
        if v not in visited:
            visited.add(v)
            yield v


class InventoryService(Service):
    def __init__(
        self,
        client: InventoryClient,
        db_access_manager: GraphDatabaseAccessManager,
        domain_event_subscriber: DomainEventSubscriber,
        redis: Redis,
    ) -> None:
        self.client = client
        self.__cached_aggregate_roots: Optional[Dict[str, Json]] = None
        self.db_access_manager = db_access_manager
        self.cache = RedisCache(redis, "inventory", ttl_memory=timedelta(minutes=5), ttl_redis=timedelta(minutes=30))
        domain_event_subscriber.subscribe(AwsAccountDeleted, self._process_account_deleted, Inventory)
        domain_event_subscriber.subscribe(TenantAccountsCollected, self._process_tenant_collected, Inventory)
        domain_event_subscriber.subscribe(CloudAccountNameChanged, self._process_account_name_changed, Inventory)
        domain_event_subscriber.subscribe(WorkspaceCreated, self._process_workspace_created, Inventory)

    async def start(self) -> Any:
        await self.cache.start()

    async def stop(self) -> Any:
        await self.cache.stop()

    async def _process_account_deleted(self, event: AwsAccountDeleted) -> None:
        set_workspace_id(str(event.tenant_id))
        set_cloud_account_id(event.aws_account_id)
        set_fix_cloud_account_id(event.cloud_account_id)
        access = await self.db_access_manager.get_database_access(event.tenant_id)
        if access:
            log.info(f"Aws Account deleted. Remove from inventory: {event}.")
            await self.client.delete_account(access, cloud=CloudNames.AWS, account_id=event.aws_account_id)

    async def _process_tenant_collected(self, event: TenantAccountsCollected) -> None:
        log.info(f"Tenant: {event.tenant_id} was collected - invalidate caches.")
        await self.evict_cache(event.tenant_id)

    async def _process_account_name_changed(self, event: CloudAccountNameChanged) -> None:
        if (name := event.final_name) and (db := await self.db_access_manager.get_database_access(event.tenant_id)):
            log.info(f"Cloud account name changed. Update in inventory: {event}.")
            q = f"is(account) and id={event.account_id} and /ancestors.cloud.reported.name={event.cloud} limit 1"
            accounts = [a async for a in await self.client.search_list(db, q)]
            if accounts and (account := accounts[0]) and (node_id := account.get("id")):
                await self.client.update_node(db, NodeId(node_id), {"name": name})
                # account name has changed: invalidate the cache for the tenant
                await self.evict_cache(event.tenant_id)
            else:
                log.info(f"Cloud account not found in inventory. Ignore. {event}.")

    async def _process_workspace_created(self, event: WorkspaceCreated) -> None:
        access = await self.db_access_manager.get_database_access(event.workspace_id)
        if access:
            log.info(f"Workspace created: {event.workspace_id}. Create related database.")
            await self.client.create_database(access)

    async def evict_cache(self, workspace_id: WorkspaceId) -> None:
        # evict the cache for the tenant in the cluster
        await self.cache.evict(str(workspace_id))

    @timed("fixbackend", "report_info")
    async def report_info(self, db: GraphDatabaseAccess) -> Json:
        async def compute_report_info() -> Json:
            benchmark_ids, check_ids = await asyncio.gather(
                self.client.benchmarks(db, ids_only=True), self.client.checks(db, ids_only=True)
            )
            return dict(benchmarks=benchmark_ids, checks=check_ids)

        return await self.cache.call(compute_report_info, key=str(db.workspace_id))()

    @timed("fixbackend", "report_config")
    async def report_config(self, db: GraphDatabaseAccess) -> ReportConfig:
        js = await self.client.config(db, "resoto.report.config")
        v = js.get("report_config", {})
        v["ignore_benchmarks"] = js.get("ignore_benchmarks", [])
        return ReportConfig.model_validate(v)

    @timed("fixbackend", "update_report_config")
    async def update_report_config(self, db: GraphDatabaseAccess, config: ReportConfig) -> None:
        js = config.model_dump()
        update = dict(ignore_benchmarks=js.pop("ignore_benchmarks", None), report_config=js)
        await self.client.update_config(db, "resoto.report.config", update)

    @timed("fixbackend", "benchmark")
    async def benchmark(
        self,
        db: GraphDatabaseAccess,
        benchmark_name: str,
        *,
        accounts: Optional[List[str]] = None,
        severity: Optional[str] = None,
        only_failing: bool = False,
    ) -> AsyncIteratorWithContext[Json]:
        report = f"report benchmark load {benchmark_name}"
        if accounts:
            report += f" --accounts {' '.join(accounts)}"
        if severity:
            report += f" --severity {severity}"
        if only_failing:
            report += " --only-failing"

        return await self.client.execute_single(db, report + " | dump")  # type: ignore

    @timed("fixbackend", "search_table")
    async def search_table(
        self,
        db: GraphDatabaseAccess,
        request: SearchRequest,
        result_format: Literal["table", "csv"] = "table",
    ) -> AsyncIteratorWithContext[JsonElement]:
        if history := request.history:
            cmd = "history"
            if history.change:
                cmd += f" --change {history.change.value}"
            if history.before:
                cmd += f" --before {utc_str(history.before)}"
            if history.after:
                cmd += f" --after {utc_str(history.after)}"
            cmd += " " + request.query
        else:
            cmd = "search " + request.query
        fmt_option = "--csv" if result_format == "csv" else "--json-table"
        cmd += f" | limit {request.skip}, {request.limit} | list {fmt_option}"
        return await self.client.execute_single(db, cmd, env={"count": json.dumps(request.count)})

    @timed("fixbackend", "search_start_data")
    async def search_start_data(self, db: GraphDatabaseAccess) -> SearchStartData:
        async def compute_search_start_data() -> SearchStartData:
            async def cloud_resource(search_filter: str, id_prop: str, name_prop: str) -> List[SearchCloudResource]:
                cmd = (
                    f"search {search_filter} | "
                    f"aggregate {id_prop} as id, {name_prop} as name, /ancestors.cloud.reported.name as cloud: "
                    f"sum(1) as count | jq --no-rewrite .group"
                )
                return sorted(
                    [
                        SearchCloudResource.model_validate(n)
                        async for n in await self.client.execute_single(db, f"{cmd}")
                        if isinstance(n, dict) and n.get("cloud") is not None
                    ],
                    key=lambda x: x.name,
                )

            (accounts, regions, kinds, roots) = await asyncio.gather(
                cloud_resource("is(account)", "id", "name"),
                cloud_resource("is(region)", "id", "name"),
                cloud_resource("all", "kind", "kind"),
                self.__aggregate_roots(db),
            )

            # lookup the kind name from the model
            for k in kinds:
                if (kind := roots.get(k.id)) and (kn := value_in_path(kind, ["metadata", "name"])):
                    k.name = kn

            return SearchStartData(accounts=accounts, regions=regions, kinds=kinds, severity=ReportSeverityList)

        return await self.cache.call(compute_search_start_data, key=str(db.workspace_id))()

    @timed("fixbackend", "resource")
    async def resource(self, db: GraphDatabaseAccess, resource_id: NodeId) -> Json:
        async def neighborhood(cmd: str) -> List[JsonElement]:
            return [n async for n in await self.client.execute_single(db, cmd, env={"with-kind": "true"})]

        jq_reported = "{id: .reported.id, name: .reported.name, kind: .reported.kind}"
        jq_arg = (
            # properties to include in the result
            "{id:.id,type:.type,from:.from,to:.to,metadata:.kind.metadata,age:.reported.age,tags:.reported.tags,"
            # also include the defined reported section for every node (not edge)
            f"reported: (if .reported!=null then {jq_reported} else null end) }}"
            # strip null values from the result
            '| walk(if type == "object" then with_entries(select(.value != null)) else . end)'
        )
        cmd = f"""search --with-edges id("{resource_id}") <-[0:2]-> | jq --no-rewrite '{jq_arg}'"""
        resource, nb = await asyncio.gather(self.client.resource(db, id=resource_id), neighborhood(cmd))
        check_ids = [sc["check"] for sc in (value_in_path(resource, ["security", "issues"]) or [])]
        checks = await self.client.checks(db, check_ids=check_ids) if check_ids else []
        checks = sorted(checks, key=lambda x: ReportSeverityPriority[x.get("severity", "info")], reverse=True)
        return dict(resource=resource, failing_checks=checks, neighborhood=nb)

    @timed("fixbackend", "summary")
    async def summary(self, db: GraphDatabaseAccess) -> ReportSummary:
        async def compute_summary() -> ReportSummary:
            now = utc()

            async def issues_since(
                duration: timedelta, change: Literal["node_vulnerable", "node_compliant"]
            ) -> VulnerabilitiesChanged:
                accounts_by_severity: Dict[str, Set[str]] = defaultdict(set)
                resource_count_by_severity: Dict[str, int] = defaultdict(int)
                resource_count_by_kind: Dict[str, int] = defaultdict(int)
                async for elem in await self.client.execute_single(
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
                top_accounts = list(
                    islice(dict_values_by(accounts_by_severity, lambda x: ReportSeverityPriority[x]), 3)
                )
                return VulnerabilitiesChanged(
                    since=duration,
                    accounts_selection=top_accounts,
                    resource_count_by_severity=resource_count_by_severity,
                    resource_count_by_kind_selection=reduced,
                )

            async def account_summary() -> Tuple[Dict[str, int], Dict[str, AccountSummary]]:
                account_by_id: Dict[str, AccountSummary] = {}
                resources_by_account: Dict[str, int] = defaultdict(int)
                resources_by_account_by_severity: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                resources_by_severity: Dict[str, int] = defaultdict(int)
                async for entry in await self.client.aggregate(
                    db,
                    "search /ancestors.account.reported.id!=null | aggregate "
                    "/ancestors.account.reported.id as account_id, "
                    "/ancestors.account.reported.name as account_name, "
                    "/ancestors.cloud.reported.name as cloud_name, "
                    "/security.severity as severity: sum(1) as count",
                ):
                    account_id = entry["group"]["account_id"]
                    count = entry["count"]
                    severity = entry["group"]["severity"]
                    if account_id not in account_by_id:
                        account_by_id[account_id] = AccountSummary(
                            id=account_id,
                            name=entry["group"]["account_name"],
                            cloud=entry["group"]["cloud_name"],
                            failed_resources_by_severity={},
                            resource_count=0,
                        )
                    resources_by_account[account_id] += count
                    if severity is not None:
                        resources_by_account_by_severity[account_id][severity] = count
                        resources_by_severity[severity] += count
                for account_id, account in account_by_id.items():
                    account.resource_count = resources_by_account.get(account_id, 0)
                    account.failed_resources_by_severity = resources_by_account_by_severity[account_id]
                return resources_by_severity, account_by_id

            async def check_summary() -> Tuple[ChecksByAccountId, SeverityByCheckId]:
                check_accounts: ChecksByAccountId = defaultdict(dict)
                check_severity: Dict[str, str] = {}

                async for entry in await self.client.aggregate(
                    db,
                    "search /security.has_issues==true | aggregate "
                    "/security.issues[].check as check_id,"
                    "/security.issues[].severity as severity,"
                    "/ancestors.account.reported.id as account_id"
                    ": sum(1) as count",
                ):
                    group = entry["group"]
                    count = entry["count"]
                    check_id = group["check_id"]
                    if isinstance(account_id := group["account_id"], str):
                        check_accounts[check_id][account_id] = count
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

            async def timeseries_infected() -> TimeSeries:
                # TODO: start should be based on tenant creation date up to some max value (e.g. 1 year)
                start = now - timedelta(days=14)
                granularity = timedelta(days=1)
                groups = {"severity"}
                data = [
                    entry
                    async for entry in await self.client.timeseries(
                        db, "infected_resources", start=start, end=now, granularity=granularity, group=groups
                    )
                ]
                return TimeSeries(name="infected_resources", start=start, end=now, granularity=granularity, data=data)

            async def top_issues(checks_by_severity: Dict[str, Set[str]], num: int) -> List[Json]:
                check_ids = dict_values_by(checks_by_severity, lambda x: ReportSeverityPriority[x])
                top = list(islice(check_ids, num))
                checks = await self.client.checks(db, check_ids=top)
                return sorted(checks, key=lambda x: ReportSeverityPriority[x.get("severity", "info")], reverse=True)

            def bench_account_score(failing_checks: Dict[str, int], benchmark_checks: Dict[str, int]) -> int:
                # Compute the score of an account with respect to a benchmark
                # Weight failing checks by severity and compute an overall percentage
                missing = sum(ReportSeverityScore[severity] * count for severity, count in failing_checks.items())
                total = sum(ReportSeverityScore[severity] * count for severity, count in benchmark_checks.items())
                return int((max(0, total - missing) * 100) // total) if total > 0 else 100

            def overall_score(accounts: Dict[str, AccountSummary]) -> int:
                # The overall score is the average of all account scores
                total_score = sum(account.score for account in accounts.values())
                total_accounts = len(accounts)
                return total_score // total_accounts if total_accounts > 0 else 100

            default_time_since = timedelta(days=7)

            (
                (severity_resource_counter, accounts),
                (benchmarks, checks),
                (failed_accounts_by_check_id, severity_by_check_id),
                vulnerable_changed,
                compliant_changed,
                infected_resources_ts,
            ) = await asyncio.gather(
                account_summary(),
                benchmark_summary(),
                check_summary(),
                issues_since(default_time_since, "node_vulnerable"),
                issues_since(default_time_since, "node_compliant"),
                timeseries_infected(),
            )

            # combine benchmark and account data
            account_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            severity_check_counter: Dict[str, int] = defaultdict(int)
            account_check_sum_count: Dict[str, int] = defaultdict(int)
            failed_checks_by_severity: Dict[str, Set[str]] = defaultdict(set)
            available_checks = 0
            for bid, bench in benchmarks.items():
                benchmark_account_issue_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                benchmark_account_resource_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                benchmark_severity_count: Dict[str, int] = defaultdict(int)
                for check_info in checks.get(bid, []):
                    check_id = check_info["id"]
                    benchmark_severity_count[check_info["severity"]] += 1
                    available_checks += 1
                    if severity := severity_by_check_id.get(check_id):
                        severity_check_counter[severity] += 1
                        for account_id, failed_resource_count in failed_accounts_by_check_id[check_id].items():
                            benchmark_account_issue_counter[account_id][severity] += 1
                            benchmark_account_resource_counter[account_id][severity] += failed_resource_count
                            account_counter[account_id][severity] += 1
                            account_check_sum_count[severity] += 1
                            failed_checks_by_severity[severity].add(check_id)
                for account_id, account in accounts.items():
                    if account.cloud in bench.clouds:
                        failing = benchmark_account_issue_counter.get(account_id)
                        failed_resource_checks = benchmark_account_resource_counter.get(account_id)
                        bench.account_summary[account_id] = BenchmarkAccountSummary(
                            score=bench_account_score(failing or {}, benchmark_severity_count),
                            failed_checks=failing,
                            failed_resource_checks=failed_resource_checks,
                        )

            # compute a score for every account by averaging the scores of all benchmark results
            for account_id, failing in account_counter.items():
                scores = [
                    ba.score for b in benchmarks.values() for aid, ba in b.account_summary.items() if aid == account_id
                ]
                accounts[account_id].score = sum(scores) // len(scores) if scores else 100

            # get issues for the top 5 issue_ids
            tops = await top_issues(failed_checks_by_severity, num=5)

            # sort top changed account by score
            vulnerable_changed.accounts_selection.sort(key=lambda x: accounts[x].score if x in accounts else 100)
            compliant_changed.accounts_selection.sort(key=lambda x: accounts[x].score if x in accounts else 100)

            return ReportSummary(
                check_summary=CheckSummary(
                    available_checks=available_checks,
                    failed_checks=sum(v for v in severity_check_counter.values()),
                    failed_checks_by_severity=severity_check_counter,
                    available_resources=sum(v.resource_count for v in accounts.values()),
                    failed_resources=sum(v for v in severity_resource_counter.values()),
                    failed_resources_by_severity=severity_resource_counter,
                ),
                overall_score=overall_score(accounts),
                accounts=sorted(list(accounts.values()), key=lambda x: x.score),
                benchmarks=list(benchmarks.values()),
                changed_vulnerable=vulnerable_changed,
                changed_compliant=compliant_changed,
                top_checks=tops,
                vulnerable_resources=infected_resources_ts,
            )

        try:
            return await self.cache.call(compute_summary, key=str(db.workspace_id))()
        # TODO: the exception handling can be removed once all existing users have a database.
        except InventoryException as ex:
            log.warning(f"Inventory not available yet: {ex}. Returning empty summary.")
            empty = CheckSummary(
                available_checks=0,
                failed_checks=0,
                failed_checks_by_severity={},
                available_resources=0,
                failed_resources=0,
                failed_resources_by_severity={},
            )
            return ReportSummary(
                check_summary=empty,
                overall_score=0,
                accounts=[],
                benchmarks=[],
                changed_vulnerable=NoVulnerabilitiesChanged,
                changed_compliant=NoVulnerabilitiesChanged,
                top_checks=[],
            )

    async def __aggregate_roots(self, db: GraphDatabaseAccess) -> Dict[str, Json]:
        if self.__cached_aggregate_roots is not None:
            return self.__cached_aggregate_roots
        else:
            root_list = await self.client.model(
                db, aggregate_roots_only=True, with_properties=False, with_relatives=False
            )
            result = {k["fqn"]: k for k in root_list}
            self.__cached_aggregate_roots = result
            return result
