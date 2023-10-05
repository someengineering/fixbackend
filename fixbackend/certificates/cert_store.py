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

from typing import Optional, Tuple

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509 import Certificate, CertificateSigningRequest, CertificateSigningRequestBuilder
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from fixbackend.certificates.ca_client import FixCaClient
from fixbackend.keyvalue.json_kv import JsonStore

CERT_KEY = "cert_manager:certificate"


class CertificateStore:
    def __init__(self, fixca_client: FixCaClient, json_store: JsonStore) -> None:
        self.fixca_client = fixca_client
        self.store = json_store

    async def _store_cert(self, cert: Certificate, private_key: Ed25519PrivateKey) -> None:
        cert_bytes_str = cert.public_bytes(serialization.Encoding.PEM)
        key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        json = {
            "cert": cert_bytes_str.decode("utf-8"),
            "private_key": key.decode("utf-8"),
        }

        await self.store.set(CERT_KEY, json)

    def _generate_private_key(self) -> Ed25519PrivateKey:
        key = Ed25519PrivateKey.generate()
        return key

    def _get_ceritificate_signing_request(
        self, private_key: Ed25519PrivateKey, common_name: str = "fixcloud.io"
    ) -> CertificateSigningRequest:
        csr = (
            CertificateSigningRequestBuilder(
                subject_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
            .sign(private_key, algorithm=None)
        )
        return csr

    async def generate_signing_certificate(
        self,
    ) -> Tuple[Certificate, Ed25519PrivateKey]:
        if cached := await self.get_cached_certificate():
            return cached
        key = self._generate_private_key()
        csr = self._get_ceritificate_signing_request(key)
        cert = await self.fixca_client.sign(csr)
        await self._store_cert(cert, key)
        return cert, key

    async def get_cached_certificate(self) -> Optional[Tuple[Certificate, Ed25519PrivateKey]]:
        json = await self.store.get(CERT_KEY)
        match json:
            case {"cert": cert, "private_key": private_key} if isinstance(cert, str) and isinstance(private_key, str):
                cert_bytes = cert.encode("utf-8")
                cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())

                key_bytes = private_key.encode("utf-8")
                key = serialization.load_pem_private_key(key_bytes, password=None, backend=default_backend())
                if not isinstance(key, Ed25519PrivateKey):
                    raise ValueError("Expected Ed25519PrivateKey")

                return cert, key
            case _:
                return None
        return None
