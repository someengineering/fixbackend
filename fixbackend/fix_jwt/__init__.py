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


import hashlib
from typing import Any, Dict, List, Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from fixbackend.certificates.cert_store import CertificateStore


def kid(key: rsa.RSAPublicKey) -> str:
    return hashlib.sha256(key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.PKCS1)).hexdigest()[
        0:8
    ]


ALGORITHM = "RS256"


def encode_token(
    payload: Dict[str, Any],
    audience: List[str],
    private_key: rsa.RSAPrivateKey,
) -> str:
    headers = {
        "kid": kid(private_key.public_key()),
    }
    payload["aud"] = audience

    return jwt.encode(payload, private_key, algorithm=ALGORITHM, headers=headers)


def decode_token(token: str, audience: List[str], public_keys: List[rsa.RSAPublicKey]) -> Optional[Dict[str, Any]]:
    # try to decode the token without verifying the signature to get the key id
    try:
        unverified = jwt.api_jwt.decode_complete(token, options={"verify_signature": False})
    except jwt.exceptions.DecodeError:  # token is not a valid JWT
        return None

    header = unverified["header"]
    key_id = header.get("kid")

    public_key = None

    # poor man JWKS
    available_keys = {kid(key): key for key in public_keys}

    if not (key_id in available_keys):
        return None

    public_key = available_keys[key_id]

    try:
        data: Dict[str, Any] = jwt.decode(jwt=token, key=public_key, algorithms=[ALGORITHM], audience=audience)
        return data
    except jwt.PyJWTError:
        return None


class JwtService:
    def __init__(self, cert_store: CertificateStore) -> None:
        self.cert_store = cert_store

    async def encode(self, payload: Dict[str, Any], audience: List[str]) -> str:
        key_pair = await self.cert_store.get_signing_cert_key_pair()
        newest_key = key_pair[0].private_key
        return encode_token(payload, audience, newest_key)

    async def decode(self, token: str, audience: List[str]) -> Optional[Dict[str, Any]]:
        key_pair = await self.cert_store.get_signing_cert_key_pair()
        public_keys = [key.private_key.public_key() for key in key_pair]
        return decode_token(token, audience, public_keys)
