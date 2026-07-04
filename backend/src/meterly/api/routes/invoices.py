from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from meterly.api.deps import ContainerDep, CustomersDep, InvoicesDep, PageDep
from meterly.billing.invoicing import run_close_cycle, store_documents
from meterly.billing.schemas import (
    CloseRunOut,
    InvoiceOut,
    InvoiceSummary,
    RerateOut,
    RerateRequest,
)
from meterly.billing.statuses import InvoiceStatus

router = APIRouter(prefix="/v1", tags=["invoices"])


class InvoicePage(BaseModel):
    items: list[InvoiceSummary]
    total: int
    limit: int
    offset: int


@router.get("/invoices")
async def list_invoices(
    service: InvoicesDep,
    customers: CustomersDep,
    page: PageDep,
    status: InvoiceStatus | None = None,
    customer_id: Annotated[str | None, Query()] = None,
) -> InvoicePage:
    customer = await customers.require(customer_id) if customer_id else None
    items, total = await service.page(
        status=status,
        customer_id=customer.id if customer else None,
        limit=page.limit,
        offset=page.offset,
    )
    return InvoicePage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: UUID, service: InvoicesDep) -> InvoiceOut:
    return await service.get(invoice_id)


@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse)
async def invoice_html(invoice_id: UUID, service: InvoicesDep) -> HTMLResponse:
    return HTMLResponse(await service.html(invoice_id))


@router.get("/invoices/{invoice_id}/pdf", response_class=Response)
async def invoice_pdf(invoice_id: UUID, service: InvoicesDep) -> Response:
    filename, content = await service.pdf(invoice_id)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/finalize")
async def finalize_invoice(
    invoice_id: UUID, service: InvoicesDep, c: ContainerDep, tasks: BackgroundTasks
) -> InvoiceOut:
    invoice = await service.finalize(invoice_id)
    tasks.add_task(store_documents, c.sessions, c.settings, c.renderer, [invoice.id])
    return invoice


@router.post("/invoices/{invoice_id}/rerate")
async def rerate_invoice(
    invoice_id: UUID, request: RerateRequest, service: InvoicesDep
) -> RerateOut:
    """Re-price the frozen usage of a draft with new prices and return a line-level diff."""
    return await service.rerate(invoice_id, request)


@router.post("/billing/run")
async def run_billing(c: ContainerDep, tasks: BackgroundTasks) -> CloseRunOut:
    """Run one period-close cycle now instead of waiting for the worker's schedule."""
    cycle = await run_close_cycle(c.sessions, c.settings, c.renderer)
    if cycle.finalized:
        tasks.add_task(store_documents, c.sessions, c.settings, c.renderer, cycle.finalized)
    return CloseRunOut(
        drafted=cycle.drafted,
        finalized=cycle.finalized,
        failed_subscriptions=cycle.failed_subscriptions,
        failed_invoices=cycle.failed_invoices,
    )
