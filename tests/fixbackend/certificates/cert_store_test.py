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


from datetime import datetime, timedelta
from typing import Dict, Optional

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.x509 import Certificate, CertificateBuilder, CertificateSigningRequest
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization
from fixcloudutils.types import JsonElement


from fixbackend.certificates.ca_client import FixCaClient
from fixbackend.certificates.cert_store import CertificateStore
from fixbackend.keyvalue.json_kv import JsonStore


class FixCaClienMock(FixCaClient):
    async def sign(self, csr: CertificateSigningRequest) -> Certificate:
        assert isinstance(csr.public_key(), Ed25519PublicKey)
        private_key = Ed25519PrivateKey.generate()
        cert = (
            CertificateBuilder(
                subject_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test_ca")]),
                issuer_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test_ca")]),
            )
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=10))
            .sign(private_key=private_key, algorithm=None)
        )
        return cert


class JsonStoreMock(JsonStore):
    def __init__(self) -> None:
        self.store: Dict[str, JsonElement] = {}

    async def get(self, key: str) -> Optional[JsonElement]:
        return self.store.get(key)

    async def set(self, key: str, value: JsonElement) -> None:
        assert key == "cert_manager:certificate"
        assert isinstance(value, dict)
        assert "cert" in value
        assert "private_key" in value
        self.store[key] = value

    async def delete(self, key: str) -> None:
        raise NotImplementedError()


@pytest.mark.asyncio
async def test_generate_cert() -> None:
    json_store = JsonStoreMock()
    fixca_client = FixCaClienMock()
    cert_store = CertificateStore(fixca_client, json_store)

    cert, key = await cert_store.generate_signing_certificate()
    assert isinstance(cert.public_key(), Ed25519PublicKey)
    assert isinstance(key, Ed25519PrivateKey)

    if certs := await cert_store.get_cached_certificate():
        cached_cert, cached_key = certs
        assert cached_cert.public_bytes(serialization.Encoding.PEM) == cert.public_bytes(serialization.Encoding.PEM)
        assert cached_key.private_bytes_raw() == key.private_bytes_raw()
    else:
        assert False, "No cached certificate found"
