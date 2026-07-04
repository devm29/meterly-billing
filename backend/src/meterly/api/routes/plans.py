from fastapi import APIRouter, status

from meterly.api.deps import PlansDep
from meterly.billing.schemas import PlanCreate, PlanOut
from meterly.billing.terms import PlanTerms

router = APIRouter(prefix="/v1/plans", tags=["plans"])


@router.get("")
async def list_plans(service: PlansDep) -> list[PlanOut]:
    return await service.all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_plan(payload: PlanCreate, service: PlansDep) -> PlanOut:
    return await service.create(payload)


@router.get("/{code}")
async def get_plan(code: str, service: PlansDep) -> PlanOut:
    return await service.get(code)


@router.post("/{code}/versions", status_code=status.HTTP_201_CREATED)
async def publish_version(code: str, terms: PlanTerms, service: PlansDep) -> PlanOut:
    return await service.publish_version(code, terms)
