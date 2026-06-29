from fastapi import APIRouter
from sqlalchemy import text

from meterly.api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(c: ContainerDep) -> dict[str, str]:
    async with c.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    if c.redis is not None:
        await c.redis.ping()
    return {"status": "ready"}
