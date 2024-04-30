from attrs import frozen
from typing import Optional, Union

from cattrs.preconf.json import make_converter
from attrs import evolve
from fixbackend.ids import FixCloudAccountId, CloudAccountId, TaskId
from uuid import UUID
from datetime import datetime

json_converter = make_converter()

json_converter.register_structure_hook(UUID, lambda v, _: UUID(v))
json_converter.register_unstructure_hook(UUID, lambda v: str(v))


@frozen
class CollectionFailure:
    duration_seconds: int
    task_id: TaskId
    error: str


@frozen
class CollectionSuccess:
    scanned_resources: int
    duration_seconds: int
    task_id: TaskId


CollectionResult = Union[CollectionFailure, CollectionSuccess]


@frozen
class AccountCollectProgress:
    cloud_account_id: FixCloudAccountId
    account_id: CloudAccountId
    started_at: datetime
    collection_done: Optional[CollectionResult] = None

    def done(
        self,
        scanned_resources: int,
        scan_duration: int,
        task_id: TaskId,
    ) -> "AccountCollectProgress":
        return evolve(self, collection_done=CollectionSuccess(scanned_resources, scan_duration, task_id))

    def failed(self, error: str, scan_duration: int, task_id: TaskId) -> "AccountCollectProgress":
        return evolve(self, collection_done=CollectionFailure(scan_duration, task_id, error))

    def is_done(self) -> bool:
        return self.collection_done is not None

    def to_json_str(self) -> str:
        return json_converter.dumps(self)

    @staticmethod
    def from_json_str(value: bytes | str) -> "AccountCollectProgress":
        return json_converter.loads(value, AccountCollectProgress)
