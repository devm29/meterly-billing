from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from meterly.billing.calculator import ComputedLine, subtotal
from meterly.money import Currency, Money


class LineDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    description: str
    before: Money | None
    after: Money | None
    delta: Money


class RerateDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    lines: list[LineDiff]
    subtotal_before: Money
    subtotal_after: Money
    delta: Money


def diff_lines(
    before: list[ComputedLine], after: list[ComputedLine], currency: Currency
) -> RerateDiff:
    old = {line.key: line for line in before}
    new = {line.key: line for line in after}
    ordered_keys = list(old) + [k for k in new if k not in old]
    zero = Money.zero(currency)

    diffs: list[LineDiff] = []
    for key in ordered_keys:
        was, now = old.get(key), new.get(key)
        before_amount = was.amount if was else None
        after_amount = now.amount if now else None
        source = now or was
        assert source is not None
        diffs.append(
            LineDiff(
                key=key,
                description=source.description,
                before=before_amount,
                after=after_amount,
                delta=(after_amount or zero) - (before_amount or zero),
            )
        )

    total_before, total_after = subtotal(before, currency), subtotal(after, currency)
    return RerateDiff(
        lines=diffs,
        subtotal_before=total_before,
        subtotal_after=total_after,
        delta=total_after - total_before,
    )
