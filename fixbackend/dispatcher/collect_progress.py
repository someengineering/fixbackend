from attrs import frozen
from typing import List, Optional, Union

from cattrs.preconf.json import make_converter
from attrs import evolve
from fixbackend.ids import FixCloudAccountId, CloudAccountId, TaskId, CloudName
from uuid import UUID
from datetime import datetime
import json

json_converter = make_converter()

json_converter.register_structure_hook(UUID, lambda v, _: UUID(v))
json_converter.register_unstructure_hook(UUID, lambda v: str(v))


@frozen
class CollectionFailure:
    duration_seconds: int
    task_id: Optional[TaskId]
    error: str


@frozen
class CollectionSuccess:
    scanned_resources: int
    duration_seconds: int
    task_id: TaskId
    resource_errors: List[str]


CollectionResult = Union[CollectionFailure, CollectionSuccess]


@frozen
class AccountCollectProgress:
    cloud: CloudName
    cloud_account_id: FixCloudAccountId
    account_id: CloudAccountId
    started_at: datetime
    collection_done: Optional[CollectionResult] = None

    def done(
        self,
        scanned_resources: int,
        scan_duration: int,
        task_id: TaskId,
        resource_errors: List[str],
    ) -> "AccountCollectProgress":
        return evolve(
            self, collection_done=CollectionSuccess(scanned_resources, scan_duration, task_id, resource_errors)
        )

    def failed(self, error: str, scan_duration: int, task_id: Optional[TaskId]) -> "AccountCollectProgress":
        return evolve(self, collection_done=CollectionFailure(scan_duration, task_id, error))

    def is_done(self) -> bool:
        return self.collection_done is not None

    def to_json_str(self) -> str:
        return json_converter.dumps(self)

    @staticmethod
    def from_json_str(value: bytes | str) -> "AccountCollectProgress":

        # delete me after deploying this to production
        dict_value = json.loads(value)

        def init_resource_errors() -> None:
            if not (collection_done := dict_value.get("collection_done")):
                return

            if not isinstance(collection_done, dict):
                return

            # we found CollectionFailure
            if collection_done.get("error"):
                return

            # resource_errors already initialized
            if collection_done.get("resource_errors"):
                return

            collection_done["resource_errors"] = []

            nonlocal value
            value = json.dumps(dict_value)

        init_resource_errors()

        return json_converter.loads(value, AccountCollectProgress)
