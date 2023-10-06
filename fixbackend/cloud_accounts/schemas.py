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

from pydantic import BaseModel, Field

from fixbackend.ids import TenantId, ExternalId


class AwsCloudFormationLambdaCallbackParameters(BaseModel):
    workspace_id: TenantId = Field(description="Your FIX-assigned Workspace ID")
    external_id: ExternalId = Field(description="Your FIX-assigned External ID")
    account_id: str = Field(description="AWS account ID", pattern=r"^\d{12}$")
    role_name: str = Field(description="AWS role name", max_length=64)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workspace_id": "00000000-0000-0000-0000-000000000000",
                    "external_id": "00000000-0000-0000-0000-000000000000",
                    "account_id": "123456789012",
                    "role_name": "FooBarRole",
                }
            ]
        }
    }
