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

from uuid import UUID

from pydantic import BaseModel, Field


class AwsCloudFormationLambdaCallbackParameters(BaseModel):
    tenant_id: UUID = Field(description="Identifier of the tenant")
    external_id: UUID = Field(description="Secret that was provided by the tenant")
    account_id: str = Field(description="AWS account ID")
    role_name: str = Field(description="AWS role name")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "external_id": "00000000-0000-0000-0000-000000000000",
                    "account_id": "123456789012",
                    "role_name": "FooBarRole",
                }
            ]
        }
    }
