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
                    "role_name": "arn:aws:iam::123456789012:role/FooBarRole",
                }
            ]
        }
    }
