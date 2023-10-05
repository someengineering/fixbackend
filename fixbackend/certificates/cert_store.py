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
from typing import Annotated, Tuple

from attrs import frozen
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509 import Certificate
from fastapi import Depends

from fixbackend.config import Config, ConfigDependency


@frozen
class CertKeyPair:
    cert: Certificate
    private_key: RSAPrivateKey


class CertificateStore:
    def __init__(self, config: Config) -> None:
        self.host_cert_path = config.host_cert
        self.host_key_path = config.host_key
        self.signing_cert_1_path = config.signing_cert_1
        self.signing_key_1_path = config.signing_key_1
        self.signing_cert_2_path = config.signing_cert_2
        self.signing_key_2_path = config.signing_key_2

    def load_cert_key_pair(self, cert_path: Path, key_path: Path) -> CertKeyPair:
        # blocking, but will be cached by the OS on the second call
        with open(self.host_cert_path, "rb") as f:
            cert_bytes = f.read()
        with open(self.host_key_path, "rb") as f:
            key_bytes = f.read()
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
        key = serialization.load_pem_private_key(key_bytes, password=None, backend=default_backend())
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("Expected RSA private key")
        return CertKeyPair(cert=cert, private_key=key)

    async def get_host_cert_key_pair(self) -> CertKeyPair:
        return self.load_cert_key_pair(self.host_cert_path, self.host_key_path)

    async def get_signing_cert_key_pair(self) -> Tuple[CertKeyPair, CertKeyPair]:
        """
        Returns the two signing certificates and their private keys, ordered by expiration date, newest first.
        """
        return (
            self.load_cert_key_pair(self.signing_cert_1_path, self.signing_key_1_path),
            self.load_cert_key_pair(self.signing_cert_2_path, self.signing_key_2_path),
        )


def get_certificate_store(config: ConfigDependency) -> CertificateStore:
    return CertificateStore(config)


CertificateStoreDependency = Annotated[CertificateStore, Depends(get_certificate_store)]
