#  Copyright (c) 2024. Some Engineering
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
from __future__ import annotations

from httpx import Response


class HttpXResponse:

    def __init__(self, response: Response) -> None:
        self.response = response

    __match_args__ = ("response",)

    @staticmethod
    def read(response: Response) -> HttpXResponse:
        match response.status_code // 100:
            case 1:
                return InformationalResponses(response)
            case 2:
                return SuccessResponse(response)
            case 3:
                return RedirectResponses(response)
            case 4:
                return ClientError(response)
            case _:
                return ServerError(response)


class SuccessResponse(HttpXResponse):

    def __str__(self) -> str:
        return f"SuccessResponse({self.response.status_code})"


class ErrorResponse(HttpXResponse):
    pass


class InformationalResponses(HttpXResponse):
    def __str__(self) -> str:
        return f"InformationalResponses({self.response.status_code: {self.response.text}})"


class RedirectResponses(HttpXResponse):
    def __str__(self) -> str:
        return f"RedirectResponses({self.response.status_code}: {self.response.headers.get('Location')})"


class ClientError(ErrorResponse):
    def __str__(self) -> str:
        return f"ClientError({self.response.status_code}: {self.response.text})"


class ServerError(ErrorResponse):
    def __str__(self) -> str:
        return f"ServerError({self.response.status_code}: {self.response.text})"
