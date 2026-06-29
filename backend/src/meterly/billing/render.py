from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import cache
from importlib import resources
from typing import Protocol

from fpdf import FPDF
from jinja2 import Environment, StrictUndefined, select_autoescape

from meterly.billing.schemas import InvoiceOut
from meterly.config import Settings
from meterly.log import get_logger
from meterly.money import Currency, Money

log = get_logger(__name__)

_SYMBOLS = {Currency.USD: "$", Currency.EUR: "€", Currency.GBP: "£", Currency.JPY: "¥"}


def format_money(value: Money) -> str:
    sign = "-" if value.amount < 0 else ""
    places = value.currency.exponent
    return f"{sign}{_SYMBOLS[value.currency]}{abs(value.amount):,.{places}f}"


def format_quantity(value: Decimal | str) -> str:
    rounded = Decimal(value).quantize(Decimal("0.01"))
    return f"{rounded:,.0f}" if rounded == rounded.to_integral_value() else f"{rounded:,.2f}"


def format_date(value: date) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def _money_filter(value: Money) -> str:
    return format_money(value)


@cache
def _environment() -> Environment:
    env = Environment(autoescape=select_autoescape(["html"]), undefined=StrictUndefined)
    env.filters["money"] = _money_filter
    env.filters["qty"] = format_quantity
    env.filters["day"] = format_date
    return env


def _template_source() -> str:
    return resources.files("meterly.templates").joinpath("invoice.html").read_text("utf-8")


class PdfBackend(Protocol):
    def render(self, html: str, invoice: InvoiceOut) -> bytes: ...


class WeasyPrintBackend:
    def render(self, html: str, invoice: InvoiceOut) -> bytes:
        from weasyprint import HTML

        pdf: bytes = HTML(string=html).write_pdf()
        return pdf


class FpdfBackend:
    """Pure-Python fallback for hosts without Pango (WeasyPrint's native dependency)."""

    def __init__(self, seller_name: str, seller_address: str) -> None:
        self._seller_name = seller_name
        self._seller_address = seller_address

    def render(self, html: str, invoice: InvoiceOut) -> bytes:
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(18, 18, 18)
        pdf.add_page()
        pdf.set_text_color(29, 29, 31)

        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 10, "Invoice", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(110, 110, 115)
        status = invoice.number or "DRAFT"
        pdf.cell(0, 6, _latin(f"{status}  ·  {self._seller_name}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, _latin(self._seller_address), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        pdf.set_text_color(29, 29, 31)
        rows = [
            ("Billed to", f"{invoice.customer_name} ({invoice.customer_id})"),
            (
                "Service period",
                f"{format_date(invoice.period_start)} - {format_date(invoice.period_end)}",
            ),
            ("Status", invoice.status.capitalize()),
        ]
        for label, value in rows:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(40, 6, label)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, _latin(value), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(110, 110, 115)
        pdf.cell(110, 7, "Description")
        pdf.cell(30, 7, "Quantity", align="R")
        pdf.cell(0, 7, "Amount", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(229, 229, 234)
        pdf.line(18, pdf.get_y(), 192, pdf.get_y())

        pdf.set_text_color(29, 29, 31)
        for line in invoice.lines:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(110, 8, _latin(line.description)[:70])
            pdf.cell(30, 8, format_quantity(line.quantity), align="R")
            pdf.cell(
                0, 8, _latin(format_money(line.amount)), align="R", new_x="LMARGIN", new_y="NEXT"
            )
            components = line.details.components if len(line.details.components) > 1 else []
            for component in components:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(110, 110, 115)
                pdf.cell(6, 5, "")
                pdf.cell(104, 5, _latin(component.label))
                pdf.cell(30, 5, format_quantity(component.units), align="R")
                pdf.cell(
                    0,
                    5,
                    _latin(format_money(component.amount)),
                    align="R",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
                pdf.set_text_color(29, 29, 31)
        pdf.line(18, pdf.get_y() + 1, 192, pdf.get_y() + 1)
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(140, 8, "Total due", align="R")
        pdf.cell(
            0, 8, _latin(format_money(invoice.total)), align="R", new_x="LMARGIN", new_y="NEXT"
        )
        return bytes(pdf.output())


def _latin(text: str) -> str:
    replacements = {"€": "EUR ", "¥": "JPY ", "–": "-", "—": "-", "·": "-", "×": "x"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _detect_backend(settings: Settings) -> PdfBackend:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        log.info("pdf.backend", backend="fpdf2", reason="weasyprint unavailable")
        return FpdfBackend(settings.seller_name, settings.seller_address)
    log.info("pdf.backend", backend="weasyprint")
    return WeasyPrintBackend()


class InvoiceRenderer:
    def __init__(self, settings: Settings, backend: PdfBackend | None = None) -> None:
        self._settings = settings
        self._backend = backend
        self._template = _environment().from_string(_template_source())

    def html(self, invoice: InvoiceOut) -> str:
        return self._template.render(
            invoice=invoice,
            seller_name=self._settings.seller_name,
            seller_address=self._settings.seller_address,
        )

    def pdf(self, invoice: InvoiceOut) -> bytes:
        if self._backend is None:
            self._backend = _detect_backend(self._settings)
        return self._backend.render(self.html(invoice), invoice)
