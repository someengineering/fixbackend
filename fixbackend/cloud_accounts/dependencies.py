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

from typing import Annotated

from fastapi import Depends

from fixbackend.cloud_accounts.service import CloudAccountService
from fixbackend.cloud_accounts.service_impl import CloudAccountServiceImpl
from fixbackend.dependencies import FixDependency, ServiceNames


def get_cloud_account_service(
    fix_dependency: FixDependency,
) -> CloudAccountService:
    return fix_dependency.service(ServiceNames.cloud_account_service, CloudAccountServiceImpl)


CloudAccountServiceDependency = Annotated[CloudAccountService, Depends(get_cloud_account_service)]
