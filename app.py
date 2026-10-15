
import json
import os
import re
import calendar
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Keep orders.ndjson in the same folder as app.py.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "orders.ndjson")
BUSINESS_TZ = ZoneInfo("Asia/Kolkata")

# USD value of one unit of each currency.
USD_PER_UNIT = {
    "USD": Decimal("1"),
    "EUR": Decimal("1.12"),
    "INR": Decimal("0.01173"),
}

app = FastAPI(title="Acme Appliances Order Ledger")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BUSINESS_TZ)

        return parsed.astimezone(BUSINESS_TZ)

    except (ValueError, TypeError):
        return None


def load_current_orders():
    """Keep only the latest updated_at row for each order ID."""
    if not os.path.exists(DATA_FILE):
        raise RuntimeError(
            "orders.ndjson must be in the same folder as app.py"
        )

    current = {}

    with open(DATA_FILE, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            try:
                order = json.loads(line)
            except json.JSONDecodeError:
                continue

            order_id = order.get("id")
            if not order_id:
                continue

            order_id = str(order_id)
            new_time = parse_datetime(order.get("updated_at"))

            if order_id not in current:
                current[order_id] = order
                continue

            old_time = parse_datetime(
                current[order_id].get("updated_at")
            )

            if (
                new_time is not None
                and (old_time is None or new_time > old_time)
            ):
                current[order_id] = order

    return list(current.values())


ORDERS = load_current_orders()

PRODUCTS = sorted(
    {
        str(order.get("product", "")).strip()
        for order in ORDERS
        if order.get("product")
    },
    key=len,
    reverse=True,
)

REGIONS = ("North", "South", "East", "West", "Central")

MONTHS = {
    name.lower(): number
    for number, name in enumerate(calendar.month_name)
    if name
}

MONTHS.update({
    name.lower(): number
    for number, name in enumerate(calendar.month_abbr)
    if name
})


def order_business_date(order):
    parsed = parse_datetime(order.get("created_at"))
    return parsed.date() if parsed else None


def amount_in_usd(order):
    currency = str(order.get("currency", "USD")).upper()
    rate = USD_PER_UNIT.get(currency)

    if rate is None:
        return Decimal("0")

    try:
        amount = Decimal(str(order.get("amount", 0)))
        return amount * rate
    except Exception:
        return Decimal("0")


def money(value):
    return float(
        Decimal(value).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )


def status_is(order, status):
    return (
        str(order.get("status", "")).strip().lower()
        == status.lower()
    )


def quantity(order):
    try:
        return int(order.get("qty", 0) or 0)
    except (TypeError, ValueError):
        return 0


def date_predicate(question):
    """Filter dates using Asia/Kolkata business dates."""
    q = question.lower()

    # Supports YYYY-MM-DD and YYYY-MM.
    iso = re.search(
        r"\b(20\d{2})-(\d{1,2})(?:-(\d{1,2}))?\b",
        q
    )

    if iso:
        year = int(iso.group(1))
        month = int(iso.group(2))
        day = int(iso.group(3)) if iso.group(3) else None

        try:
            if day is not None:
                target = date(year, month, day)
                return lambda order: (
                    order_business_date(order) == target
                )

            return lambda order: (
                (d := order_business_date(order)) is not None
                and d.year == year
                and d.month == month
            )

        except ValueError:
            return lambda order: False

    words = re.findall(r"[a-z]+", q)

    month = next(
        (MONTHS[word] for word in words if word in MONTHS),
        None
    )

    year_match = re.search(r"\b(20\d{2})\b", q)
    year = int(year_match.group(1)) if year_match else None

    if month is not None and year is not None:
        return lambda order: (
            (d := order_business_date(order)) is not None
            and d.year == year
            and d.month == month
        )

    if year is not None:
        return lambda order: (
            (d := order_business_date(order)) is not None
            and d.year == year
        )

    if month is not None:
        return lambda order: (
            (d := order_business_date(order)) is not None
            and d.month == month
        )

    return lambda order: True


def extract_filters(question, ignore_product=False):
    q = question.lower()
    date_ok = date_predicate(question)

    region = next(
        (
            name for name in REGIONS
            if re.search(r"\b" + re.escape(name.lower()) + r"\b", q)
        ),
        None
    )

    product = None

    if not ignore_product:
        product = next(
            (
                name for name in PRODUCTS
                if name.lower() in q
            ),
            None
        )

    customer_match = re.search(
        r"\bC\d+\b", question, re.IGNORECASE
    )
    customer = (
        customer_match.group(0).upper()
        if customer_match else None
    )

    def matches(order):
        if not date_ok(order):
            return False

        if region and str(order.get("region", "")).lower() != region.lower():
            return False

        if product and str(order.get("product", "")).lower() != product.lower():
            return False

        if customer and str(order.get("customer", "")).upper() != customer:
            return False

        return True

    return matches, region, product, customer


def answer_question(question):
    original = question.strip()

    if not original:
        raise ValueError("Question must not be empty")

    q = re.sub(r"\s+", " ", original.lower())

    asks_top = bool(re.search(
        r"\b(top(?:[- ]selling)?|best[- ]selling|bestselling|"
        r"most|highest|largest|greatest|number[- ]one)\b",
        q
    ))

    asks_product_rank = "product" in q and asks_top
    asks_customer_rank = "customer" in q and asks_top

    asks_refund = bool(re.search(
        r"\b(refund|refunds|refunded|refunding)\b", q
    ))

    asks_void = bool(re.search(
        r"\b(void|cancelled|canceled|cancellation)\b", q
    ))

    asks_units = bool(re.search(
        r"\b(units?|quantity|quantities|items)\b", q
    )) and bool(re.search(
        r"\b(sold|ordered|total|how many|most|top|highest|selling)\b",
        q
    ))

    asks_count = bool(re.search(
        r"\b(how many|number of|count|count of|quantity of)\b", q
    ))

    asks_average = bool(re.search(
        r"\b(average|avg|mean)\b", q
    ))

    asks_distinct_customers = (
        "customer" in q
        and not asks_customer_rank
        and (
            bool(re.search(r"\b(different|distinct|unique)\b", q))
            or (
                "customers" in q
                and asks_count
            )
        )
        and not (
            re.search(r"\borders?\b", q)
            and re.search(r"\bcustomer\s+C?\d+\b", q, re.I)
        )
    )

    matches, region, product, customer = extract_filters(
        original,
        ignore_product=asks_product_rank
    )

    selected = [
        order for order in ORDERS
        if matches(order)
    ]

    # Refund questions use the current refunded status.
    if asks_refund:
        rows = [
            order for order in selected
            if status_is(order, "refunded")
        ]

        if asks_count:
            return len(rows)

        return money(sum(
            (amount_in_usd(order) for order in rows),
            Decimal("0")
        ))

    # Void questions are handled separately from revenue.
    if asks_void:
        rows = [
            order for order in selected
            if status_is(order, "void")
        ]

        if asks_count:
            return len(rows)

        return money(sum(
            (amount_in_usd(order) for order in rows),
            Decimal("0")
        ))

    # Count unique customers, not order rows.
    if asks_distinct_customers:
        rows = selected

        if "paid" in q:
            rows = [
                order for order in rows
                if status_is(order, "paid")
            ]

        return len({
            str(order.get("customer", "")).upper()
            for order in rows
            if order.get("customer")
        })

    # Revenue calculations and rankings use paid orders only.
    paid = [
        order for order in selected
        if status_is(order, "paid")
    ]

    # Find the best-selling product.
    if asks_product_rank:
        by_units = bool(re.search(
            r"\b(units?|quantity|quantities|volume)\b", q
        ))

        by_orders = (
            bool(re.search(r"\b(orders?|transactions)\b", q))
            and not by_units
        )

        totals = defaultdict(
            int if (by_units or by_orders) else Decimal
        )

        for order in paid:
            name = str(order.get("product", "")).strip()

            if by_units:
                totals[name] += quantity(order)
            elif by_orders:
                totals[name] += 1
            else:
                totals[name] += amount_in_usd(order)

        if not totals:
            return None

        return max(totals, key=totals.get)

    # Find the top customer by orders or revenue.
    if asks_customer_rank:
        by_orders = (
            bool(re.search(r"\b(orders?|transactions)\b", q))
            and not bool(re.search(
                r"\b(revenue|sales|spent|spending|amount|value|dollars?)\b",
                q
            ))
        )

        totals = defaultdict(int if by_orders else Decimal)

        for order in paid:
            name = str(order.get("customer", "")).strip()

            if name:
                totals[name] += (
                    1 if by_orders else amount_in_usd(order)
                )

        if not totals:
            return None

        return max(totals, key=totals.get)

    # Count orders. If "paid" is specified, count paid orders only.
    if asks_count and not asks_units:
        rows = selected

        if "paid" in q:
            rows = [
                order for order in rows
                if status_is(order, "paid")
            ]

        return len(rows)

    # Sum quantities from paid orders.
    if asks_units:
        return sum(quantity(order) for order in paid)

    total_revenue = sum(
        (amount_in_usd(order) for order in paid),
        Decimal("0")
    )

    if asks_average:
        if not paid:
            return None

        return money(total_revenue / len(paid))

    if any(term in q for term in (
        "revenue", "sales", "sold", "turnover", "total",
        "amount", "value", "usd", "dollar", "how much",
        "generated", "made"
    )):
        return money(total_revenue)

    # If a specific product, customer or region is named,
    # return that entity's paid revenue by default.
    if customer or product or region:
        return money(total_revenue)

    return {
        "message": (
            "I could not identify the requested metric. Ask about "
            "paid revenue, refunds, void orders, order counts, units, "
            "distinct customers, or the top product/customer."
        )
    }


@app.get("/")
def home():
    return {
        "service": "Acme Appliances order ledger",
        "status": "ok",
        "orders_loaded": len(ORDERS),
        "endpoint": "POST /answer"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "orders_loaded": len(ORDERS)
    }


@app.post("/answer")
@app.post("/ask")
def ask(payload: QuestionRequest):
    try:
        return {"answer": answer_question(payload.question)}
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not answer question: {exc}"
        )
