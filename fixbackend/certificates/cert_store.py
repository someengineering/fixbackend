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

from pathlib import Path
from typing import List
from datetime import datetime, timedelta
import os

from aiofiles import open as aopen
from async_lru import alru_cache
from attrs import frozen
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.x509 import Certificate

from fixbackend.config import Config


@frozen
class CertKeyPair:
    cert: Certificate
    private_key: RSAPrivateKey


@alru_cache(maxsize=100, ttl=60)
async def load_cert_key_pair(cert_path: Path, key_path: Path) -> CertKeyPair:
    # blocking, but will be cached by the OS on the second call
    async with aopen(cert_path, "rb") as f:
        cert_bytes = await f.read()
    async with aopen(key_path, "rb") as f:
        key_bytes = await f.read()
    cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
    key = serialization.load_pem_private_key(key_bytes, password=None, backend=default_backend())
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("Expected RSA private key")
    return CertKeyPair(cert=cert, private_key=key)


async def get_localhost_key_pair() -> List[CertKeyPair]:
    local_signing_key_path = Path("/tmp/fixbackend/local_jwt_signing.key")
    local_signing_crt_path = Path("/tmp/fixbackend/local_jwt_signing.crt")

    if local_signing_key_path.exists() and local_signing_crt_path.exists():
        key_pair = await load_cert_key_pair(local_signing_crt_path, local_signing_key_path)
        return [key_pair]

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "fixbackend jwt ephemeral signing key")]))
        .issuer_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "fixbackend running locally")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )

    local_signing_crt_path.parent.mkdir(parents=True, exist_ok=True)
    local_signing_key_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_signing_key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    with open(local_signing_crt_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return [CertKeyPair(cert=cert, private_key=key)]


class CertificateStore:
    def __init__(self, config: Config) -> None:
        self.host_cert_path = config.host_cert
        self.host_key_path = config.host_key
        self.signing_cert_1_path = config.signing_cert_1
        self.signing_key_1_path = config.signing_key_1
        self.signing_cert_2_path = config.signing_cert_2
        self.signing_key_2_path = config.signing_key_2

    async def get_host_cert_key_pair(self) -> CertKeyPair:
        assert self.host_cert_path is not None
        assert self.host_key_path is not None
        return await load_cert_key_pair(self.host_cert_path, self.host_key_path)

    async def _get_signing_cert_key_pair(self) -> List[CertKeyPair]:
        """
        Returns the two signing certificates and their private keys, ordered by expiration date, newest first.
        """
        bundle = [
            await load_cert_key_pair(self.signing_cert_1_path, self.signing_key_1_path),
            await load_cert_key_pair(self.signing_cert_2_path, self.signing_key_2_path),
        ]
        bundle.sort(key=lambda pair: pair.cert.not_valid_after_utc, reverse=True)
        return bundle

    # this wrapper is needed to avoid the pain during testing and local development
    async def get_signing_cert_key_pair(self) -> List[CertKeyPair]:
        if os.environ.get("LOCAL_DEV_ENV") is not None:
            cert_key_pairs = await get_localhost_key_pair()
        else:
            cert_key_pairs = await self._get_signing_cert_key_pair()

        return cert_key_pairs

    async def private_key(self) -> RSAPrivateKey:
        cert_key_pairs = await self.get_signing_cert_key_pair()
        return cert_key_pairs[0].private_key

    async def public_keys(self) -> List[RSAPublicKey]:
        cert_key_pairs = await self.get_signing_cert_key_pair()
        return [ckp.private_key.public_key() for ckp in cert_key_pairs]
