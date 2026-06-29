from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from meterly.api.deps import ContainerDep
from meterly.config import Settings
from meterly.errors import ForbiddenError, UnauthorizedError


class Scope(StrEnum):
    INGEST = "ingest"
    ADMIN = "admin"


_api_key = APIKeyHeader(
    name="x-api-key",
    auto_error=False,
    description="Admin key for the console and billing operations; ingest key for product code.",
)


def _same(presented: str, expected: str) -> bool:
    # Hash first so the comparison is constant-time regardless of the presented length.
    return hmac.compare_digest(
        hashlib.sha256(presented.encode()).digest(), hashlib.sha256(expected.encode()).digest()
    )


def scopes_for(key: str, settings: Settings) -> frozenset[Scope]:
    if _same(key, settings.admin_api_key.get_secret_value()):
        return frozenset(Scope)
    if _same(key, settings.ingest_api_key.get_secret_value()):
        return frozenset({Scope.INGEST})
    return frozenset()


def require(scope: Scope) -> Callable[[ContainerDep, str | None], Awaitable[None]]:
    async def check(c: ContainerDep, key: Annotated[str | None, Security(_api_key)]) -> None:
        if not key:
            raise UnauthorizedError("missing x-api-key header")
        granted = scopes_for(key, c.settings)
        if not granted:
            raise UnauthorizedError("invalid API key")
        if scope not in granted:
            raise ForbiddenError(f"this API key cannot perform {scope} operations")

    return check


RequireIngest = Depends(require(Scope.INGEST))
RequireAdmin = Depends(require(Scope.ADMIN))
