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
from datetime import timedelta, datetime
from itertools import islice
from typing import (
    List,
    Optional,
    Dict,
    Set,
    Tuple,
    Literal,
    TypeVar,
    Iterable,
    Callable,
    Any,
    Mapping,
    Union,
    AsyncContextManager,
)

from arq import func
from arq.connections import RedisSettings
from attr import frozen
from fixcloudutils.redis.cache import RedisCache
from fixcloudutils.redis.worker_queue import WorkDispatcher, WorkerInstance
from fixcloudutils.service import Service
from fixcloudutils.types import Json, JsonElement
from fixcloudutils.util import value_in_path, utc_str, utc, parse_utc_str, value_in_path_get

from fixbackend.cloud_accounts.repository import CloudAccountRepository
from fixbackend.config import ProductTierSettings, Trial
from fixbackend.domain_events.events import (
    CloudAccountDeleted,
    TenantAccountsCollected,
    CloudAccountNameChanged,
    WorkspaceCreated,
    ProductTierChanged,
    CloudAccountScanToggled,
    CloudAccountActiveToggled,
)
from fixbackend.domain_events.subscriber import DomainEventSubscriber
from fixbackend.graph_db.models import GraphDatabaseAccess
from fixbackend.graph_db.service import GraphDatabaseAccessManager
from fixbackend.ids import NodeId
from fixbackend.ids import TaskId, WorkspaceId
from fixbackend.inventory.inventory_client import (
    InventoryClient,
    AsyncIteratorWithContext,
    InventoryException,
    NoSuchGraph,
)
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
    Scatter,
    Scatters,
)
from fixbackend.logging_context import set_cloud_account_id, set_fix_cloud_account_id, set_workspace_id
from fixbackend.types import Redis

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
ReportSeverityIncluded: Dict[str, List[str]] = {n: ReportSeverityList[idx:] for idx, n in enumerate(ReportSeverityList)}
Inventory = "inventory-service"
DecoratedFn = TypeVar("DecoratedFn", bound=Callable[..., Any])


def dict_values_by(d: Mapping[T, Iterable[V]], fn: Callable[[T], Any]) -> Iterable[V]:
    # Sort the dict using the given function and return unique values in the order of the sorted keys
    visited = set()
    for v in (v for _, values in sorted(d.items(), key=lambda x: fn(x[0]), reverse=True) for v in values):
        if v not in visited:
            visited.add(v)
            yield v


@frozen
class InventorySummary:
    resources_per_account_timeline: Scatters
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


class InventoryService(Service):
    def __init__(
        self,
        client: InventoryClient,
        db_access_manager: GraphDatabaseAccessManager,
        cloud_account_repository: CloudAccountRepository,
        domain_event_subscriber: Optional[DomainEventSubscriber],
        redis: Redis,
        redis_settings: RedisSettings,
        start_workers: bool = True,
    ) -> None:
        self.client = client
        self.__cached_aggregate_roots: Optional[Dict[str, Json]] = None
        self.db_access_manager = db_access_manager
        self.cloud_account_repository = cloud_account_repository
        self.cache = RedisCache(redis, "inventory", ttl_memory=timedelta(minutes=5), ttl_redis=timedelta(minutes=30))
        worker_queue_name = "arq:inventory_service_queue"
        self.dispatcher = WorkDispatcher(redis_settings, worker_queue_name)
        self.worker = WorkerInstance(
            redis_settings=redis_settings,
            queue_name=worker_queue_name,
            functions=[func(self._update_cloud_account_name_again, name="update_cloud_account_name_again")],
        )
        self.update_name_again_after = timedelta(hours=1)
        self.start_workers = start_workers
        if sub := domain_event_subscriber:
            sub.subscribe(CloudAccountDeleted, self._process_account_deleted, Inventory)
            sub.subscribe(TenantAccountsCollected, self._process_tenant_collected, Inventory)
            sub.subscribe(CloudAccountNameChanged, self._process_account_name_changed, Inventory)
            sub.subscribe(WorkspaceCreated, self._process_workspace_created, Inventory)
            sub.subscribe(ProductTierChanged, self._process_product_tier_changed, Inventory)
            sub.subscribe(CloudAccountScanToggled, self._configure_disabled_accounts, Inventory)
            sub.subscribe(CloudAccountActiveToggled, self._configure_disabled_accounts, Inventory)

    async def start(self) -> Any:
        if self.start_workers:
            await self.cache.start()
            await self.worker.start()
            await self.dispatcher.start()

    async def stop(self) -> Any:
        if self.start_workers:
            await self.dispatcher.stop()
            await self.worker.stop()
            await self.cache.stop()

    async def _process_account_deleted(self, event: CloudAccountDeleted) -> None:
        set_workspace_id(event.tenant_id)
        set_cloud_account_id(event.account_id)
        set_fix_cloud_account_id(event.cloud_account_id)
        access = await self.db_access_manager.get_database_access(event.tenant_id)
        if access:
            log.info(f"Aws Account deleted. Remove from inventory: {event}.")
            await self.client.delete_account(access, cloud=event.cloud, account_id=event.account_id)

    async def _process_tenant_collected(self, event: TenantAccountsCollected) -> None:
        log.info(f"Tenant: {event.tenant_id} was collected - invalidate caches.")
        await self.evict_cache(event.tenant_id)

    async def _process_account_name_changed(self, event: CloudAccountNameChanged) -> None:
        # update the name now
        if await self._update_cloud_account_name(event):
            # update the name again after 1 hour to capture all inflight collections
            await self.dispatcher.enqueue(
                "update_cloud_account_name_again", event, _defer_by=self.update_name_again_after
            )

    async def _update_cloud_account_name_again(self, ctx: Dict[str, str], event: CloudAccountNameChanged) -> None:
        log.info(f"Update cloud account name again: {event}")
        await self._update_cloud_account_name(event)

    async def _update_cloud_account_name(self, event: CloudAccountNameChanged) -> bool:
        if (name := event.final_name) and (db := await self.db_access_manager.get_database_access(event.tenant_id)):
            log.info(f"Cloud account name changed. Update in inventory: {event}.")
            q = f"is(account) and id={event.account_id} and /ancestors.cloud.reported.name={event.cloud} limit 1"
            async with self.client.search(db, q) as result:
                accounts = [a async for a in result]
            if accounts and (account := accounts[0]) and (node_id := account.get("id")):
                await self.client.update_node(db, NodeId(node_id), {"name": name}, force=True)
                # account name has changed: invalidate the cache for the tenant
                await self.evict_cache(event.tenant_id)
                return True
            else:
                log.info(f"Cloud account not found in inventory. Ignore. {event}.")
        return False

    async def _process_workspace_created(self, event: WorkspaceCreated) -> None:
        access = await self.db_access_manager.get_database_access(event.workspace_id)
        if access:
            log.info(f"Workspace created: {event.workspace_id}. Create related database.")
            await self.client.create_database(access)
            await self.change_db_retention_period(event.workspace_id, Trial.retention_period)

    async def _process_product_tier_changed(self, event: ProductTierChanged) -> None:
        log.info(f"Product tier changed: {event.workspace_id}: {event.product_tier}")
        setting = ProductTierSettings[event.product_tier]
        await self.change_db_retention_period(event.workspace_id, setting.retention_period)

    async def change_db_retention_period(self, workspace_id: WorkspaceId, retention_period: timedelta) -> None:
        access = await self.db_access_manager.get_database_access(workspace_id)
        if access:
            log.info(f"Change retention period for database: {workspace_id}: {retention_period}")
            await self.client.update_config(
                access,
                "fix.core",
                {"fixcore": {"graph_update": {"keep_history_for_days": retention_period.days}}},
                patch=True,
            )

    async def _configure_disabled_accounts(
        self, event: Union[CloudAccountScanToggled, CloudAccountActiveToggled]
    ) -> None:
        if db := await self.db_access_manager.get_database_access(event.tenant_id):
            acs = await self.cloud_account_repository.list_by_workspace_id(event.tenant_id, ready_for_collection=True)
            disabled = [a.account_id for a in acs if not a.enabled_for_scanning()]
            log.info(f"Cloud account scan toggled. Following accounts are disabled: {disabled}.")
            await self.client.update_config(
                db, "fix.report.config", {"report_config": {"ignore_accounts": disabled}}, patch=True
            )

    async def evict_cache(self, workspace_id: WorkspaceId) -> None:
        # evict the cache for the tenant in the cluster
        await self.cache.evict(str(workspace_id))

    async def checks(
        self,
        db: GraphDatabaseAccess,
        provider: Optional[str] = None,
        service: Optional[str] = None,
        category: Optional[str] = None,
        kind: Optional[str] = None,
        check_ids: Optional[List[str]] = None,
        ids_only: Optional[bool] = None,
    ) -> List[Json]:
        async def fetch_checks(*_: Any) -> List[Json]:
            return await self.client.checks(
                db,
                provider=provider,
                service=service,
                category=category,
                kind=kind,
                check_ids=check_ids,
                ids_only=ids_only,
            )

        return await self.cache.call(fetch_checks, key=str(db.workspace_id))(
            provider, service, category, kind, check_ids, ids_only  # parameters passed as cache key
        )

    async def benchmarks(
        self,
        db: GraphDatabaseAccess,
        benchmarks: Optional[List[str]] = None,
        short: Optional[bool] = None,
        with_checks: Optional[bool] = None,
        ids_only: Optional[bool] = None,
    ) -> List[Json]:
        async def fetch_benchmarks(*_: Any) -> List[Json]:
            return await self.client.benchmarks(
                db, benchmarks=benchmarks, short=short, with_checks=with_checks, ids_only=ids_only
            )

        return await self.cache.call(fetch_benchmarks, key=str(db.workspace_id))(
            benchmarks, short, with_checks, ids_only  # parameters passed as cache key
        )

    async def report_info(self, db: GraphDatabaseAccess) -> Json:
        async def compute_report_info() -> Json:
            benchmark_ids, check_ids = await asyncio.gather(
                self.client.benchmarks(db, ids_only=True), self.client.checks(db, ids_only=True)
            )
            return dict(benchmarks=benchmark_ids, checks=check_ids)

        return await self.cache.call(compute_report_info, key=str(db.workspace_id))()

    async def report_config(self, db: GraphDatabaseAccess) -> ReportConfig:
        js = await self.client.config(db, "fix.report.config")
        v = js.get("report_config", {})
        v["ignore_benchmarks"] = js.get("ignore_benchmarks", [])
        return ReportConfig.model_validate(v)

    async def update_report_config(self, db: GraphDatabaseAccess, config: ReportConfig) -> None:
        js = config.model_dump()
        update = dict(ignore_benchmarks=js.pop("ignore_benchmarks", None), report_config=js)
        await self.client.update_config(db, "fix.report.config", update)

    def benchmark(
        self,
        db: GraphDatabaseAccess,
        benchmark_name: str,
        *,
        accounts: Optional[List[str]] = None,
        severity: Optional[str] = None,
        only_failing: bool = False,
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        report = f"report benchmark load {benchmark_name}"
        if accounts:
            report += f" --accounts {' '.join(accounts)}"
        if severity:
            report += f" --severity {severity}"
        if only_failing:
            report += " --only-failing"

        return self.client.execute_single(db, report + " | dump")  # type: ignore

    def search_table(
        self,
        db: GraphDatabaseAccess,
        request: SearchRequest,
        result_format: Literal["table", "csv"] = "table",
    ) -> AsyncContextManager[AsyncIteratorWithContext[JsonElement]]:
        if history := request.history:
            cmd = "history"
            for change in history.all_changes():
                cmd += f" --change {change}"
            if history.before:
                cmd += f" --before {utc_str(history.before)}"
            if history.after:
                cmd += f" --after {utc_str(history.after)}"
            cmd += " " + request.query
        else:
            cmd = "search " + request.query
        if request.sort:
            cmd += " | sort " + ", ".join(f"{s.path} {s.direction}" for s in request.sort)
        fmt_option = "--csv" if result_format == "csv" else "--json-table"
        cmd += f" | limit {request.skip}, {request.limit} | list {fmt_option}"
        return self.client.execute_single(db, cmd, env={"count": json.dumps(request.count)})

    async def search_start_data(self, db: GraphDatabaseAccess) -> SearchStartData:
        async def compute_search_start_data() -> SearchStartData:
            async def cloud_resource(search_filter: str, id_prop: str, name_prop: str) -> List[SearchCloudResource]:
                cmd = (
                    f"search {search_filter} | "
                    f"aggregate {id_prop} as id, {name_prop} as name, /ancestors.cloud.reported.name as cloud: "
                    f"sum(1) as count | jq --no-rewrite .group"
                )
                async with self.client.execute_single(db, f"{cmd}") as result:
                    return sorted(
                        [
                            SearchCloudResource.model_validate(n)
                            async for n in result
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

    async def resource(self, db: GraphDatabaseAccess, resource_id: NodeId) -> Json:
        resource = await self.client.resource(db, id=resource_id)
        check_ids = [sc["check"] for sc in (value_in_path(resource, ["security", "issues"]) or [])]
        ignored_checks = value_in_path(resource, ["metadata", "security_ignore"])
        if isinstance(ignored_checks, list):
            check_ids.extend(ignored_checks)
        checks = await self.client.checks(db, check_ids=check_ids) if check_ids else []
        checks = sorted(checks, key=lambda x: ReportSeverityPriority[x.get("severity", "info")], reverse=True)
        return dict(resource=resource, checks=checks)

    def neighborhood(
        self, db: GraphDatabaseAccess, resource_id: NodeId
    ) -> AsyncContextManager[AsyncIteratorWithContext[Json]]:
        jq_reported = "{id: .reported.id, name: .reported.name, kind: .reported.kind}"
        jq_arg = (
            # properties to include in the result
            "{id:.id,type:.type,from:.from,to:.to,metadata:.kind.metadata,age:.reported.age,tags:.reported.tags,"
            # also include the defined reported section for every node (not edge)
            f"reported: (if .reported!=null then {jq_reported} else null end) }}"
            # strip null values from the result
            '| walk(if type == "object" then with_entries(select(.value != null)) else . end)'
        )
        cmd = (
            f"""search --with-edges id("{resource_id}") <-[0:2]-> | refine-resource-data | jq --no-rewrite '{jq_arg}'"""
        )
        return self.client.execute_single(db, cmd, env={"with-kind": "true"})  # type: ignore

    async def summary(self, db: GraphDatabaseAccess) -> ReportSummary:
        async def compute_summary() -> ReportSummary:
            now = utc()

            async def issues_since(
                duration: timedelta, change: Literal["node_vulnerable", "node_compliant"]
            ) -> VulnerabilitiesChanged:
                accounts_by_severity: Dict[str, Set[str]] = defaultdict(set)
                resource_count_by_severity: Dict[str, int] = defaultdict(int)
                resource_count_by_kind: Dict[str, int] = defaultdict(int)
                async with self.client.execute_single(
                    db,
                    f"history --change node_vulnerable --change node_compliant "
                    f"--after {duration.total_seconds()}s | aggregate "
                    f"/ancestors.account.reported.id as account_id, "
                    f"/diff.{change}[*].severity as severity,"
                    f"kind as kind"
                    ": sum(1) as count | dump",
                ) as result:
                    async for elem in result:
                        assert isinstance(elem, dict), f"Expected Json object but got {elem}"
                        severity = elem["group"]["severity"]
                        if severity is None:  # safeguard for history entries in old format
                            continue
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
                async with self.client.aggregate(
                    db,
                    "search /ancestors.account.reported.id!=null | aggregate "
                    "/ancestors.account.reported.id as account_id, "
                    "/ancestors.account.reported.name as account_name, "
                    "/ancestors.cloud.reported.name as cloud_name, "
                    "/security.severity as severity: sum(1) as count",
                ) as result:
                    async for entry in result:
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
                async with self.client.aggregate(
                    db,
                    "search /security.has_issues==true | aggregate "
                    "/security.issues[].check as check_id,"
                    "/security.issues[].severity as severity,"
                    "/ancestors.account.reported.id as account_id"
                    ": sum(1) as count",
                ) as result:
                    async for entry in result:
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
                async with self.client.timeseries(
                    db, "infected_resources", start=start, end=now, granularity=granularity, group=groups
                ) as result:
                    data = [entry async for entry in result]
                return TimeSeries(name="infected_resources", start=start, end=now, granularity=granularity, data=data)

            async def top_issues(
                checks_by_severity: Dict[str, Set[str]],
                benchmark_by_check_id: Dict[str, Set[str]],
                benchmarks: Dict[str, BenchmarkSummary],
                num: int,
            ) -> List[Json]:
                check_ids = dict_values_by(checks_by_severity, lambda x: ReportSeverityPriority[x])
                top = list(islice(check_ids, num))
                checks = await self.client.checks(db, check_ids=top)
                for check in checks:
                    check["benchmarks"] = [
                        {"id": bs.id, "title": bs.title}
                        for b in benchmark_by_check_id[check["id"]]
                        if (bs := benchmarks.get(b))
                    ]
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
            benchmark_by_check_id: Dict[str, Set[str]] = defaultdict(set)
            available_checks = 0
            for bid, bench in benchmarks.items():
                benchmark_account_issue_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                benchmark_account_resource_counter: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
                benchmark_severity_count: Dict[str, int] = defaultdict(int)
                for check_info in checks.get(bid, []):
                    check_id = check_info["id"]
                    benchmark_by_check_id[check_id].add(bid)
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
            tops = await top_issues(failed_checks_by_severity, benchmark_by_check_id, benchmarks, num=5)

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
        except InventoryException as ex:
            # in case no account is collected yet -> no graph, this is expected.
            if not isinstance(ex, NoSuchGraph):
                log.info(f"Inventory not available yet: {ex}. Returning empty summary.")
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

    async def timeseries_scattered(
        self,
        access: GraphDatabaseAccess,
        name: str,
        *,
        start: datetime,
        end: datetime,
        granularity: timedelta,
        group: Optional[Set[str]] = None,
        filter_group: Optional[List[str]] = None,
        aggregation: Optional[str] = None,
    ) -> Scatters:
        scatters: Dict[str, Scatter] = {}
        ats: Set[datetime] = set()
        async with self.client.timeseries(
            access,
            name,
            start=start,
            end=end,
            group=group,
            filter_group=filter_group,
            granularity=granularity,
            aggregation=aggregation,
        ) as cursor:
            async for entry in cursor:
                if (atstr := entry.get("at")) and (group := entry.get("group")) and (v := entry.get("v")):
                    at = parse_utc_str(str(atstr))
                    group_name = "::".join(f"{k}={v}" for k, v in sorted(group.items()))
                    ats.add(at)
                    points = {at: v}
                    scatter = Scatter(group_name=group_name, group=group, values=points)
                    if existing := scatters.get(scatter.group_name):
                        existing.values.update(scatter.values)
                    else:
                        scatters[scatter.group_name] = scatter
        return Scatters(
            start=start,
            end=end,
            granularity=granularity,
            ats=sorted(ats),
            groups=sorted(scatters.values(), key=lambda x: x.avg, reverse=True),  # sort by scatter, biggest first
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

    def logs(
        self, db: GraphDatabaseAccess, task_id: TaskId
    ) -> AsyncContextManager[AsyncIteratorWithContext[JsonElement]]:
        cmd = f"workflows log {task_id} | dump"
        return self.client.execute_single(db, cmd)

    async def inventory_summary(self, dba: GraphDatabaseAccess, now: datetime, duration: timedelta) -> InventorySummary:

        async def compute_inventory_info(duration: timedelta) -> InventorySummary:
            start = now - duration

            async with self.client.search(dba, "is(account)") as response:
                account_names = {
                    value_in_path(acc, "reported.id"): value_in_path(acc, "reported.name") async for acc in response
                }

            async def progress(
                metric: str, not_exist: int, group: Optional[Set[str]] = None, aggregation: Optional[str] = None
            ) -> Tuple[int, int]:
                async with self.client.timeseries(
                    dba,
                    metric,
                    start=now - duration,
                    end=now,
                    granularity=duration,
                    group=group,
                    aggregation=aggregation,
                ) as response:
                    entries = [int(r["v"]) async for r in response]
                    if len(entries) == 0:  # timeseries haven't been created yet
                        return not_exist, 0
                    elif len(entries) == 1:  # the timeseries does not exist longer than the current period
                        return entries[0], 0
                    else:
                        return entries[1], entries[1] - entries[0]

            async def resources_per_account_timeline() -> Scatters:
                scatters = await self.timeseries_scattered(
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

                return scatters

            async def nr_of_changes() -> Tuple[int, int, int]:
                cmd = (
                    f"history --after {utc_str(start)} --change node_created --change node_updated --change node_deleted | "
                    "aggregate /change: sum(1) as count | dump"
                )
                async with self.client.execute_single(dba, cmd) as result:
                    changes = {value_in_path(r, "group.change"): value_in_path_get(r, "count", 0) async for r in result}
                    return (
                        changes.get("node_created", 0),
                        changes.get("node_updated", 0),
                        changes.get("node_deleted", 0),
                    )

            async def overall_score() -> Tuple[int, int]:
                current, diff = await progress("account_score", 100, group=set(), aggregation="avg")
                return current, diff

            (
                scatters,
                score_progress,
                resource_changes,
                instances_progress,
                cores_progress,
                memory_progress,
                volumes_progress,
                volume_bytes_progress,
                databases_progress,
                databases_bytes_progress,
                buckets_objects_progress,
                buckets_size_bytes_progress,
            ) = await asyncio.gather(
                resources_per_account_timeline(),
                overall_score(),
                nr_of_changes(),
                progress("instances_total", 0, group=set(), aggregation="sum"),
                progress("cores_total", 0, group=set(), aggregation="sum"),
                progress("memory_bytes", 0, group=set(), aggregation="sum"),
                progress("volumes_total", 0, group=set(), aggregation="sum"),
                progress("volume_bytes", 0, group=set(), aggregation="sum"),
                progress("databases_total", 0, group=set(), aggregation="sum"),
                progress("databases_bytes", 0, group=set(), aggregation="sum"),
                progress("buckets_objects_total", 0, group=set(), aggregation="sum"),
                progress("buckets_size_bytes", 0, group=set(), aggregation="sum"),
            )

            return InventorySummary(
                scatters,  # type: ignore
                score_progress,  # type: ignore
                resource_changes,  # type: ignore
                instances_progress,  # type: ignore
                cores_progress,  # type: ignore
                memory_progress,  # type: ignore
                volumes_progress,  # type: ignore
                volume_bytes_progress,  # type: ignore
                databases_progress,  # type: ignore
                databases_bytes_progress,  # type: ignore
                buckets_objects_progress,  # type: ignore
                buckets_size_bytes_progress,  # type: ignore
            )

        return await self.cache.call(compute_inventory_info, key=str(dba.workspace_id))(duration)
