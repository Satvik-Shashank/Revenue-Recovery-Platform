"""Canonical event schema: every gateway/billing source is normalized into these entities."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

DeclineCode = Literal[
    "insufficient_funds", "expired_card", "do_not_honor", "suspected_fraud", "auth_required",
    "lost_stolen", "invalid_card", "bank_downtime", "limit_exceeded", "other",
]
DeclineCategory = Literal["soft", "hard", "auth", "bank"]


class Base(BaseModel):
    source: str = "manual"
    source_id: Optional[str] = None


class Customer(Base):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source_ids: dict = Field(default_factory=dict)
    created_at: Optional[str] = None
    address: Optional[str] = None


class PaymentMethod(Base):
    customer_id: str
    type: Literal["card", "upi", "netbanking", "wallet"] = "card"
    network: Optional[str] = None
    bank: Optional[str] = None
    fingerprint: Optional[str] = None
    expiry: Optional[str] = None  # YYYY-MM


class PaymentAttempt(Base):
    id: str
    customer_id: str
    amount: float
    currency: str = "INR"
    status: Literal["succeeded", "failed", "pending"]
    decline_code: Optional[DeclineCode] = None
    decline_category: Optional[DeclineCategory] = None
    raw_decline_code: Optional[str] = None
    gateway: str = "razorpay"
    method_type: str = "card"
    bank: Optional[str] = None
    attempted_at: str
    is_recurring: bool = False
    subscription_id: Optional[str] = None
    fingerprint: Optional[str] = None


class Subscription(Base):
    id: str
    customer_id: str
    plan: str = "standard"
    amount: float = 0.0
    interval: Literal["monthly", "yearly", "weekly"] = "monthly"
    status: Literal["active", "past_due", "paused", "canceled"] = "active"
    next_billing_at: Optional[str] = None
    seats: int = 1


class Invoice(Base):
    id: str
    customer_id: str
    amount: float
    due_date: str
    paid_at: Optional[str] = None
    status: Literal["open", "paid", "overdue", "void"] = "open"
    line_items: list = Field(default_factory=list)


class Dispute(Base):
    id: str
    customer_id: str
    payment_id: Optional[str] = None
    reason_code: Optional[str] = None
    network: Optional[str] = None
    amount: float
    opened_at: str
    respond_by: Optional[str] = None
    status: Literal["open", "under_review", "won", "lost", "accepted"] = "open"
    outcome: Optional[str] = None
    pre_dispute: bool = False


class Refund(Base):
    id: str
    customer_id: str
    payment_id: Optional[str] = None
    amount: float
    reason: Optional[str] = None
    requested_at: str
    status: Literal["requested", "approved", "declined", "processed"] = "requested"


class Order(Base):
    id: str
    customer_id: str
    items: list = Field(default_factory=list)
    amount: float
    payment_mode: Literal["prepaid", "COD"] = "prepaid"
    address: Optional[str] = None
    pincode: Optional[str] = None
    delivery_status: str = "pending"
    created_at: Optional[str] = None


class Shipment(Base):
    order_id: str
    carrier: Optional[str] = None
    delivered_at: Optional[str] = None
    pod: bool = False
    rto: bool = False


class EngagementEvent(Base):
    customer_id: str
    type: Literal["login", "usage", "ticket", "ticket_resolved", "downgrade", "seat_reduction", "offer_taken"]
    timestamp: str
    value: float = 1.0
