from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meterly.billing.calculator import (
    ComputedLine,
    UsageSnapshot,
    check_override,
    compute_lines,
    subtotal,
)
from meterly.billing.mappers import dump_overrides, invoice_out, invoice_summary, price_overrides
from meterly.billing.render import InvoiceRenderer
from meterly.billing.repository import (
    CustomerRepository,
    InvoiceRepository,
    SubscriptionRepository,
)
from meterly.billing.rerate import diff_lines
from meterly.billing.schemas import (
    InvoiceOut,
    InvoiceSummary,
    LineDetails,
    RerateOut,
    RerateRequest,
)
from meterly.billing.snapshots import SnapshotBuilder, bill_window, next_period_end
from meterly.billing.statuses import InvoiceStatus
from meterly.config import Settings
from meterly.db.models import Invoice, InvoiceLine, Subscription
from meterly.errors import InvalidRequestError, InvoiceImmutableError, NotFoundError
from meterly.log import get_logger

log = get_logger(__name__)
MAX_CLOSE_BACKOFF = timedelta(hours=6)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _line_rows(lines: list[ComputedLine]) -> list[InvoiceLine]:
    return [
        InvoiceLine(
            position=position,
            line_key=line.key,
            kind=line.kind.value,
            charge_key=line.charge_key,
            description=line.description,
            metric_code=line.metric_code,
            plan_version_id=line.plan_version_id,
            phase_start=line.phase_start,
            phase_end=line.phase_end,
            quantity=line.quantity,
            billable_quantity=line.billable_quantity,
            amount=line.amount.amount,
            details=LineDetails.of(line).model_dump(mode="json"),
        )
        for position, line in enumerate(lines)
    ]


class InvoiceService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        renderer: InvoiceRenderer,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._settings = settings
        self._renderer = renderer
        self._clock = clock
        self._invoices = InvoiceRepository(session)
        self._subs = SubscriptionRepository(session)
        self._snapshots = SnapshotBuilder(session)

    async def page(
        self,
        *,
        status: InvoiceStatus | None,
        customer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InvoiceSummary], int]:
        rows, total = await self._invoices.page(
            status=status, customer_id=customer_id, limit=limit, offset=offset
        )
        return [invoice_summary(r) for r in rows], total

    async def get(self, invoice_id: UUID) -> InvoiceOut:
        return invoice_out(await self._load(invoice_id))

    async def html(self, invoice_id: UUID) -> str:
        return self._renderer.html(await self.get(invoice_id))

    async def pdf(self, invoice_id: UUID) -> tuple[str, bytes]:
        invoice = await self._load(invoice_id)
        filename = f"{invoice.number or f'draft-{invoice.id}'}.pdf"
        if invoice.status == InvoiceStatus.FINALIZED:
            stored = await self._invoices.stored_pdf(invoice.id)
            if stored is not None:
                return filename, stored
        return filename, await self._render_pdf(invoice_out(invoice))

    async def store_document(self, invoice_id: UUID) -> None:
        """Render a finalized invoice once and keep the bytes, outside the finalize lock."""
        invoice = await self._load(invoice_id)
        if invoice.status != InvoiceStatus.FINALIZED:
            await self._session.rollback()
            return
        content = await self._render_pdf(invoice_out(invoice))
        await self._invoices.store_pdf(invoice.id, content)
        await self._session.commit()
        log.info("invoice.rendered", invoice_id=str(invoice.id), bytes=len(content))

    async def _render_pdf(self, invoice: InvoiceOut) -> bytes:
        # WeasyPrint/fpdf are synchronous and CPU-bound; keep them off the event loop.
        return await to_thread.run_sync(self._renderer.pdf, invoice)

    async def close_next_due(self) -> CloseAttempt | None:
        """Close one subscription period whose grace window has passed.

        Runs in its own transaction: the subscription row is locked with SKIP LOCKED, the
        usage snapshot is frozen, lines are priced and the billing cursor advances, all or
        nothing. A failure is recorded on the subscription with exponential back-off so
        the rest of the queue keeps moving. Returns None when there is nothing left to close.
        """
        now = self._clock()
        closable_through = (now - timedelta(minutes=self._settings.close_grace_minutes)).date()
        ids = await self._subs.claim_due(closable_through, now, limit=1)
        if not ids:
            await self._session.rollback()
            return None
        sub = await self._subs.get(ids[0])
        if sub is None:
            raise NotFoundError(f"subscription {ids[0]} vanished while locked")
        try:
            async with self._session.begin_nested():
                invoice_id = await self._close(sub, now)
        except Exception as exc:
            attempts = sub.close_attempts + 1
            backoff = min(timedelta(minutes=2 ** min(attempts, 10)), MAX_CLOSE_BACKOFF)
            sub.close_attempts = attempts
            sub.last_close_error = f"{type(exc).__name__}: {exc}"[:2000]
            sub.next_close_attempt_at = now + backoff
            await self._session.commit()
            log.exception(
                "invoice.close_failed",
                subscription_id=str(sub.id),
                attempts=attempts,
                retry_at=sub.next_close_attempt_at.isoformat(),
            )
            return CloseAttempt(subscription_id=sub.id, invoice_id=None)
        sub.close_attempts = 0
        sub.last_close_error = None
        sub.next_close_attempt_at = None
        await self._session.commit()
        return CloseAttempt(subscription_id=sub.id, invoice_id=invoice_id)

    async def _close(self, sub: Subscription, now: datetime) -> UUID:
        # Serialises with ingestion's shared lock on the customer: every batch that passed
        # the closed-period check has committed before the snapshot reads the rollups.
        await CustomerRepository(self._session).lock(sub.customer_id)
        window = bill_window(sub)
        snapshot = await self._snapshots.for_subscription(sub, window)
        lines = compute_lines(snapshot)
        amount = subtotal(lines, snapshot.currency)
        invoice = Invoice(
            customer_id=sub.customer_id,
            subscription_id=sub.id,
            status=InvoiceStatus.DRAFT,
            currency=snapshot.currency.value,
            period_start=window.start,
            period_end=window.end,
            subtotal=amount.amount,
            total=amount.amount,
            usage_snapshot=snapshot.model_dump(mode="json"),
            created_at=now,
        )
        invoice.lines = _line_rows(lines)
        self._session.add(invoice)
        sub.billed_through = window.end
        sub.current_period_end = next_period_end(sub)
        await self._session.flush()
        log.info(
            "invoice.drafted",
            invoice_id=str(invoice.id),
            subscription_id=str(sub.id),
            period=f"{window.start}..{window.end}",
            total=str(amount),
        )
        return invoice.id

    async def finalize(self, invoice_id: UUID) -> InvoiceOut:
        """Assign the legal number and freeze the invoice; the PDF is rendered afterwards."""
        invoice = await self._load(invoice_id, lock=True)
        if invoice.status != InvoiceStatus.DRAFT:
            raise InvoiceImmutableError(
                f"invoice is {invoice.status}; only drafts can be finalized"
            )
        now = self._clock()
        sequence = await self._invoices.next_number()
        invoice.number = f"{self._settings.invoice_number_prefix}-{now.year}-{sequence:06d}"
        invoice.status = InvoiceStatus.FINALIZED
        invoice.finalized_at = now
        await self._session.commit()
        log.info("invoice.finalized", invoice_id=str(invoice.id), number=invoice.number)
        return invoice_out(invoice)

    async def finalize_next_due(self, exclude: list[UUID]) -> FinalizeAttempt | None:
        cutoff = self._clock() - timedelta(hours=self._settings.draft_review_hours)
        ids = await self._invoices.claim_due_drafts(cutoff, limit=1, exclude=exclude)
        if not ids:
            await self._session.rollback()
            return None
        try:
            await self.finalize(ids[0])
        except Exception:
            await self._session.rollback()
            log.exception("invoice.finalize_failed", invoice_id=str(ids[0]))
            return FinalizeAttempt(invoice_id=ids[0], ok=False)
        return FinalizeAttempt(invoice_id=ids[0], ok=True)

    async def undocumented(self, limit: int) -> list[UUID]:
        return await self._invoices.finalized_without_document(limit)

    async def rerate(self, invoice_id: UUID, request: RerateRequest) -> RerateOut:
        invoice = await self._load(invoice_id, lock=request.apply)
        if invoice.status != InvoiceStatus.DRAFT:
            raise InvoiceImmutableError(
                f"invoice {invoice.number} is {invoice.status}; re-rating needs a draft"
            )
        snapshot = UsageSnapshot.model_validate(invoice.usage_snapshot)
        charges = [c for phase in snapshot.phases for c in phase.terms.charges]
        unknown = request.overrides.keys() - {c.key for c in charges}
        if unknown:
            raise InvalidRequestError(f"unknown charge keys: {', '.join(sorted(unknown))}")
        for charge in charges:
            if charge.key in request.overrides:
                check_override(charge, request.overrides[charge.key])

        current = price_overrides(invoice)
        merged = {**current, **request.overrides}
        before = compute_lines(snapshot, current)
        after = compute_lines(snapshot, merged)
        diff = diff_lines(before, after, snapshot.currency)

        if request.apply:
            amount = subtotal(after, snapshot.currency)
            invoice.lines.clear()
            await self._session.flush()
            invoice.lines.extend(_line_rows(after))
            invoice.subtotal = amount.amount
            invoice.total = amount.amount
            invoice.price_overrides = dump_overrides(merged)
            await self._session.commit()
            log.info("invoice.rerated", invoice_id=str(invoice.id), delta=str(diff.delta))
        return RerateOut(applied=request.apply, diff=diff)

    async def _load(self, invoice_id: UUID, *, lock: bool = False) -> Invoice:
        invoice = await self._invoices.get(invoice_id, lock=lock)
        if invoice is None:
            raise NotFoundError(f"invoice {invoice_id} does not exist")
        return invoice


@dataclass(frozen=True, slots=True)
class CloseAttempt:
    subscription_id: UUID
    invoice_id: UUID | None


@dataclass(frozen=True, slots=True)
class FinalizeAttempt:
    invoice_id: UUID
    ok: bool


@dataclass(slots=True)
class CycleResult:
    drafted: list[UUID] = field(default_factory=list)
    finalized: list[UUID] = field(default_factory=list)
    failed_subscriptions: list[UUID] = field(default_factory=list)
    failed_invoices: list[UUID] = field(default_factory=list)


async def run_close_cycle(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    renderer: InvoiceRenderer,
    clock: Callable[[], datetime] = utc_now,
    max_items: int = 500,
) -> CycleResult:
    """Drain due periods, then due drafts, one short transaction per item.

    Each item fails on its own: a subscription that cannot be closed is backed off and the
    loop moves on, and finalization runs regardless of how closing went.
    """
    result = CycleResult()
    for _ in range(max_items):
        async with factory() as session:
            attempt = await InvoiceService(session, settings, renderer, clock).close_next_due()
        if attempt is None:
            break
        if attempt.invoice_id is None:
            result.failed_subscriptions.append(attempt.subscription_id)
        else:
            result.drafted.append(attempt.invoice_id)

    for _ in range(max_items):
        async with factory() as session:
            finalized = await InvoiceService(session, settings, renderer, clock).finalize_next_due(
                exclude=result.failed_invoices
            )
        if finalized is None:
            break
        target = result.finalized if finalized.ok else result.failed_invoices
        target.append(finalized.invoice_id)
    return result


async def store_documents(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    renderer: InvoiceRenderer,
    invoice_ids: list[UUID] | None = None,
    limit: int = 100,
) -> int:
    """Render and store PDFs for finalized invoices; a failed render is retried next sweep."""
    if invoice_ids is None:
        async with factory() as session:
            invoice_ids = await InvoiceService(session, settings, renderer).undocumented(limit)
    stored = 0
    for invoice_id in invoice_ids:
        try:
            async with factory() as session:
                await InvoiceService(session, settings, renderer).store_document(invoice_id)
            stored += 1
        except Exception:
            log.exception("invoice.render_failed", invoice_id=str(invoice_id))
    return stored
