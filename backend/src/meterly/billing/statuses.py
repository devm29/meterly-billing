from enum import StrEnum


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    VOID = "void"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    TRIALING = "trialing"
    CANCELED = "canceled"
    SCHEDULED = "scheduled"
