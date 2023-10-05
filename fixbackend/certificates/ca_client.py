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

from abc import ABC, abstractmethod

import httpx
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.x509 import Certificate, CertificateSigningRequest

from fixbackend.config import Config


class FixCaClient(ABC):
    @abstractmethod
    async def sign(self, csr: CertificateSigningRequest) -> Certificate:
        pass


class FixCaClientImpl(FixCaClient):
    def __init__(self, config: Config) -> None:
        self.ca_url = config.ca_url

    async def sign(self, csr: CertificateSigningRequest) -> Certificate:
        csr_bytes = csr.public_bytes(serialization.Encoding.PEM)
        response = httpx.post(f"{self.ca_url}/ca/sign", content=csr_bytes)
        if response.status_code != 200:
            raise ValueError(f"Failed to get signed certificate: {response.text}")

        cert_bytes = response.content
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
        return cert
