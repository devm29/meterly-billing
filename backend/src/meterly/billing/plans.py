from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.mappers import plan_out
from meterly.billing.repository import PlanRepository
from meterly.billing.schemas import PlanCreate, PlanOut
from meterly.billing.terms import PlanTerms
from meterly.db.models import Plan, PlanVersion
from meterly.errors import ConflictError, InvalidRequestError, NotFoundError
from meterly.metering.repository import MetricRepository


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plans = PlanRepository(session)
        self._metrics = MetricRepository(session)

    async def all(self) -> list[PlanOut]:
        return [plan_out(p) for p in await self._plans.all()]

    async def get(self, code: str) -> PlanOut:
        plan = await self._plans.get_by_code(code)
        if plan is None:
            raise NotFoundError(f"plan {code!r} does not exist")
        return plan_out(plan)

    async def create(self, payload: PlanCreate) -> PlanOut:
        if await self._plans.get_by_code(payload.code):
            raise ConflictError(f"plan {payload.code!r} already exists")
        await self._check_metrics(payload.terms)
        plan = Plan(code=payload.code, name=payload.name, description=payload.description)
        plan.versions = [PlanVersion(version=1, terms=payload.terms.model_dump(mode="json"))]
        self._session.add(plan)
        await self._session.commit()
        return await self.get(payload.code)

    async def publish_version(self, code: str, terms: PlanTerms) -> PlanOut:
        """Plan versions are immutable; changing prices means publishing a new version.
        Existing subscriptions stay on the version they signed up for."""
        plan = await self._plans.get_by_code(code)
        if plan is None:
            raise NotFoundError(f"plan {code!r} does not exist")
        await self._check_metrics(terms)
        latest = max((v.version for v in plan.versions), default=0)
        self._session.add(
            PlanVersion(plan_id=plan.id, version=latest + 1, terms=terms.model_dump(mode="json"))
        )
        await self._session.commit()
        self._session.expire_all()
        return await self.get(code)

    async def _check_metrics(self, terms: PlanTerms) -> None:
        known = await self._metrics.by_codes(sorted(terms.metric_codes))
        missing = terms.metric_codes - known.keys()
        if missing:
            raise InvalidRequestError(f"unknown metrics: {', '.join(sorted(missing))}")
