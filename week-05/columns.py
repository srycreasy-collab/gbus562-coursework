"""Work out from a CSV header row which columns hold what.

Companies name their columns differently: Brookfield's orders.csv has model, qty and
ship_in_days, while Copperline's has product, units and ship_by_day. Each header is split
into words ("ship_by_day" -> ship, by, day; "qtyPerBike" -> qty, per, bike) and scored
against what the role usually looks like. The best-scoring column wins. If nothing
matches, or two columns score the same, ColumnError says which headers were seen, so the
column can be renamed.

Roles found this way (the other columns, such as order_id and part_id, are fixed names):

    orders.csv             product, quantity, ship_day
    bill-of-materials.csv  product, per_unit
"""

import re


class ColumnError(Exception):
    """A role's column can't be found, or more than one column fits it."""


def words(header):
    """The lowercase words in a header: "Ship-By Day" -> ["ship", "by", "day"]."""
    header = re.sub(r"([a-z])([A-Z])", r"\1 \2", header or "")
    return re.findall(r"[a-z]+", header.lower())


def is_whole_number(value):
    return bool(re.fullmatch(r"\s*-?\d+\s*", value or ""))


PRODUCT = {"model", "product", "item", "sku", "machine", "style", "variant", "good", "goods", "finished", "assembly"}
QUANTITY = {"qty", "quantity", "units", "unit", "count", "amount", "volume", "pcs", "pieces", "ordered"}
SHIP = {"ship", "shipping", "ships", "due", "deliver", "delivery", "dispatch", "promised", "needed", "need"}
DAY = {"day", "days"}
PER = {"per", "each", "usage"}


def _product(w):
    return 3 if PRODUCT & set(w) and "part" not in w else 0


def _quantity(w):
    s = set(w)
    if s & (PER | SHIP | DAY | {"penalty", "id", "part", "price", "cost"}):
        return 0
    return 3 if s & QUANTITY else 0


def _per_unit(w):
    s = set(w)
    if s & (SHIP | DAY | {"id", "price", "cost"}):
        return 0
    score = 0
    if s & PER:
        score += 2
    if s & QUANTITY:
        score += 1
    return score


def _ship_day(w):
    s = set(w)
    if not s & SHIP:
        return 0
    return 3 if s & DAY else 1


SCORERS = {"product": _product, "quantity": _quantity, "per_unit": _per_unit, "ship_day": _ship_day}
NUMERIC_ROLES = {"quantity", "per_unit", "ship_day"}


def find_column(headers, role, file_name, rows=(), taken=()):
    """The header that holds role. rows (optional) break ties and fill gaps for number columns."""
    headers = [h for h in headers if h and h not in taken]
    scores = {h: SCORERS[role](words(h)) for h in headers}
    best = max(scores.values(), default=0)
    picks = [h for h, s in scores.items() if s == best and s > 0]

    if role in NUMERIC_ROLES and rows and len(picks) != 1:
        # Keep only columns whose every value is a whole number.
        pool = picks or headers
        numeric = [h for h in pool if all(is_whole_number(r.get(h)) for r in rows)]
        if len(numeric) == 1:
            picks = numeric

    if len(picks) == 1:
        return picks[0]
    seen = ", ".join(headers) or "none"
    if not picks:
        raise ColumnError(f"{file_name}: no column looks like the {role.replace('_', ' ')} (columns: {seen})")
    raise ColumnError(f"{file_name}: more than one column could be the {role.replace('_', ' ')}: {', '.join(picks)}")


def order_columns(headers, rows=()):
    """{"product", "quantity", "ship_day"} -> header, for orders.csv."""
    fixed = {"order_id", "customer", "contact_email", "late_penalty"}
    found = {}
    for role in ("ship_day", "product", "quantity"):
        found[role] = find_column(headers, role, "orders.csv", rows, taken=fixed | set(found.values()))
    return found


def bom_columns(headers, rows=()):
    """{"product", "per_unit"} -> header, for bill-of-materials.csv."""
    found = {"product": find_column(headers, "product", "bill-of-materials.csv", rows, taken={"part_id"})}
    found["per_unit"] = find_column(headers, "per_unit", "bill-of-materials.csv", rows, taken={"part_id", found["product"]})
    return found


def is_yes(value):
    return str(value or "").strip().lower() in {"yes", "y", "true", "1"}
