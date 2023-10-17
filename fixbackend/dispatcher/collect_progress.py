from attrs import frozen
from typing import Literal

from cattrs.preconf.json import make_converter
from attrs import evolve
from fixbackend.ids import CloudAccountId
from uuid import UUID
from datetime import datetime

json_converter = make_converter()

json_converter.register_structure_hook(UUID, lambda v, _: UUID(v))
json_converter.register_unstructure_hook(UUID, lambda v: str(v))


@frozen
class AccountCollectInProgress:
    account_id: CloudAccountId
    started_at: datetime
    status: Literal["in_progress", "done"] = "in_progress"

    def done(self) -> "AccountCollectInProgress":
        return evolve(self, status="done")

    def to_json_str(self) -> str:
        return json_converter.dumps(self)

    @staticmethod
    def from_json_bytes(value: bytes) -> "AccountCollectInProgress":
        return json_converter.loads(value, AccountCollectInProgress)
