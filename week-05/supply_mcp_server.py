"""MCP server with a company's supply data tools, for the supply analyst.

The company is a folder laid out like week-05/brookfield-bikes (--org names it; that
folder is the default):

    parts.csv              part_id, description, on_hand, supplier
    inbound.csv            po_number, part_id, supplier, qty, arrives_in_days
    orders.csv             order_id, customer, contact_email, late_penalty, plus a product,
                           a quantity, and a ship day column
    bill-of-materials.csv  part_id, plus a product and a parts-per-unit column

The product, quantity, ship day and parts-per-unit columns go by different names at
different companies (model/qty/ship_in_days/qty_per_bike at Brookfield,
product/units/ship_by_day/per_unit at Copperline). columns.py works out which is which
from each header row.

Days are counted from today, which is day 0.

Three read-only tools:

    get_part              A part's stock on hand and its scheduled shipments.
    get_orders_for_part   The open customer orders that need a part, in part units.
    check_coverage        Replaces one purchase order's shipment with a revised schedule
                          and works out, order by order, when each order has its parts.

Allocation rule: stock goes to orders in order of ship day, earliest first (ties by
order_id). An order is ready on the first day the stock on hand plus everything that
has arrived covers it and every order that ships before it. It is at risk if that
day is after its ship day.

The CSV files are read again on every call, so edits show up without a restart.

Run from the top of the repository (normally an MCP client starts it):

    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py --org week-05\\copperline-coffee

Everything it logs goes to stderr, because stdout carries the MCP protocol.
"""

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from columns import ColumnError, bom_columns, is_yes, order_columns

WEEK_DIR = Path(__file__).resolve().parent
DEFAULT_COMPANY_DIR = WEEK_DIR / "brookfield-bikes"

FILES = {
    "parts.csv": ["part_id", "description", "on_hand", "supplier"],
    "inbound.csv": ["po_number", "part_id", "supplier", "qty", "arrives_in_days"],
    "orders.csv": ["order_id", "customer", "contact_email", "late_penalty"],
    "bill-of-materials.csv": ["part_id"],
}
# The files whose other columns are found from the header row (see columns.py).
FIND_COLUMNS = {"orders.csv": order_columns, "bill-of-materials.csv": bom_columns}

ALLOCATION_RULE = (
    "Stock goes to orders by ship day, earliest first (ties by order_id). An order is ready "
    "on the first day that stock on hand plus arrived shipments covers it and every order "
    "that ships before it. ready_day is null if the schedule never covers it."
)


def log(message):
    print(message, file=sys.stderr, flush=True)


class SetupError(Exception):
    """A problem that stops the server from starting."""


class Shipment(BaseModel):
    qty: int = Field(ge=0, description="How many units arrive in this shipment.")
    arrives_in_days: int = Field(ge=0, description="When it arrives, in days from today (today is day 0).")


@dataclass
class Order:
    order_id: str
    customer: str
    product: str
    units: int
    parts_needed: int
    ship_day: int
    late_penalty: bool


# ------------------------------------------------------------------ Data


class Company:
    def __init__(self, folder):
        self.folder = folder

    def read(self, name):
        return self.read_with_columns(name)[0]

    def read_with_columns(self, name):
        """(rows, columns). columns maps each role (product, quantity...) to its header for
        the files in FIND_COLUMNS, and is empty for the others."""
        path = self.folder / name
        try:
            with path.open(newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                headers = [(h or "").strip() for h in (reader.fieldnames or [])]
                reader.fieldnames = headers
                missing = [c for c in FILES[name] if c not in headers]
                if missing:
                    raise ToolError(f"{name} is missing the column(s): {', '.join(missing)}")
                rows = [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]
        except OSError as error:
            raise ToolError(f"Couldn't read {name}: {error}")
        columns = {}
        if name in FIND_COLUMNS:
            try:
                columns = FIND_COLUMNS[name](headers, rows)
            except ColumnError as error:
                raise ToolError(str(error))
        return rows, columns

    @staticmethod
    def number(row, column, name):
        try:
            return int(row[column])
        except ValueError:
            raise ToolError(f"{name}: {column} {row[column]!r} is not a whole number")

    def part(self, part_id):
        wanted = (part_id or "").strip().upper()
        parts = self.read("parts.csv")
        for row in parts:
            if row["part_id"].upper() == wanted:
                return row
        known = ", ".join(r["part_id"] for r in parts)
        raise ToolError(f"No part {part_id!r}. Known parts: {known}")

    def inbound(self, part_id):
        rows = [r for r in self.read("inbound.csv") if r["part_id"].upper() == part_id.upper()]
        return [
            {
                "po_number": r["po_number"],
                "supplier": r["supplier"],
                "qty": self.number(r, "qty", "inbound.csv"),
                "arrives_in_days": self.number(r, "arrives_in_days", "inbound.csv"),
            }
            for r in rows
        ]

    def orders_for(self, part_id):
        bom, b = self.read_with_columns("bill-of-materials.csv")
        per_unit = {}
        for row in bom:
            if row["part_id"].upper() == part_id.upper():
                per_unit[row[b["product"]]] = self.number(row, b["per_unit"], "bill-of-materials.csv")
        rows, c = self.read_with_columns("orders.csv")
        orders = []
        for row in rows:
            product = row[c["product"]]
            if product not in per_unit:
                continue
            units = self.number(row, c["quantity"], "orders.csv")
            orders.append(
                Order(
                    order_id=row["order_id"],
                    customer=row["customer"],
                    product=product,
                    units=units,
                    parts_needed=units * per_unit[product],
                    ship_day=self.number(row, c["ship_day"], "orders.csv"),
                    late_penalty=is_yes(row["late_penalty"]),
                )
            )
        orders.sort(key=lambda o: (o.ship_day, o.order_id))
        return orders


def allocate(on_hand, shipments, orders):
    """Coverage of each order, earliest ship day first. shipments: list of (qty, day)."""
    arrivals = sorted([(0, on_hand)] + [(day, qty) for qty, day in shipments])
    days = sorted({day for day, _ in arrivals})

    def supply_by(day):
        return sum(qty for d, qty in arrivals if d <= day)

    rows = []
    needed_so_far = 0
    for order in orders:
        needed_so_far += order.parts_needed
        short = min(order.parts_needed, max(0, needed_so_far - supply_by(order.ship_day)))
        ready_day = next((d for d in days if supply_by(d) >= needed_so_far), None)
        at_risk = ready_day is None or ready_day > order.ship_day
        rows.append(
            {
                "order_id": order.order_id,
                "customer": order.customer,
                "product": order.product,
                "units_ordered": order.units,
                "parts_needed": order.parts_needed,
                "ship_day": order.ship_day,
                "ready_day": ready_day,
                "units_short": short,
                "days_late": (ready_day - order.ship_day) if (at_risk and ready_day is not None) else 0,
                "late_penalty": order.late_penalty,
                "at_risk": at_risk,
            }
        )
    return rows


# ---------------------------------------------------------------- Server


def build_server(company):
    server = MCPServer(
        name=f"{company.folder.name}-supply",
        instructions=(
            "Supply data tools. Days are counted from today (day 0). Use check_coverage for "
            "every coverage question; never work out coverage yourself."
        ),
    )
    read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=read_only)
    def get_part(part_id: str) -> str:
        """Get one part's description, supplier, stock on hand, and scheduled shipments.

        Each shipment has its purchase order number, quantity, and arrival day in days
        from today (today is day 0).
        """
        part = company.part(part_id)
        result = {
            "part_id": part["part_id"],
            "description": part["description"],
            "supplier": part["supplier"],
            "on_hand": company.number(part, "on_hand", "parts.csv"),
            "scheduled_shipments": company.inbound(part["part_id"]),
        }
        return json.dumps(result, indent=1)

    @server.tool(annotations=read_only)
    def get_orders_for_part(part_id: str) -> str:
        """List the open customer orders that need a part, earliest ship day first.

        parts_needed is in part units (units ordered times the part's quantity per unit).
        ship_day is the planned ship day, in days from today.
        """
        part = company.part(part_id)
        orders = company.orders_for(part["part_id"])
        result = {
            "part_id": part["part_id"],
            "orders": [
                {
                    "order_id": o.order_id,
                    "customer": o.customer,
                    "product": o.product,
                    "units_ordered": o.units,
                    "parts_needed": o.parts_needed,
                    "ship_day": o.ship_day,
                    "late_penalty": o.late_penalty,
                }
                for o in orders
            ],
            "total_parts_needed": sum(o.parts_needed for o in orders),
        }
        return json.dumps(result, indent=1)

    @server.tool(annotations=read_only)
    def check_coverage(part_id: str, po_number: str, revised_shipments: list[Shipment]) -> str:
        """Check which orders a revised shipment schedule puts at risk.

        Replaces the scheduled shipment of purchase order po_number with
        revised_shipments (each a quantity and an arrival day in days from today; pass
        an empty list if nothing will arrive). The part's other scheduled shipments
        stay as they are. Returns, for every order that needs the part, its ship_day,
        ready_day, units_short (part units missing on its ship day), days_late, and
        whether it is at risk, plus which orders were already at risk on the current
        schedule. Call it once per schedule, for example once for each option a
        supplier offers.

        revised_shipments must be a JSON list of objects, not a string and not an
        object that wraps the list. Example for 120 units in 5 days and 280 in 26 days:
        "revised_shipments": [{"qty": 120, "arrives_in_days": 5},
                              {"qty": 280, "arrives_in_days": 26}]
        """
        part = company.part(part_id)
        part_id = part["part_id"]
        on_hand = company.number(part, "on_hand", "parts.csv")
        inbound = company.inbound(part_id)
        po = next((s for s in inbound if s["po_number"].upper() == (po_number or "").strip().upper()), None)
        if po is None:
            pos = ", ".join(s["po_number"] for s in inbound) or "none"
            raise ToolError(f"{po_number!r} is not a scheduled shipment of {part_id}. Its shipments: {pos}")

        others = [s for s in inbound if s is not po]
        orders = company.orders_for(part_id)
        current = allocate(on_hand, [(s["qty"], s["arrives_in_days"]) for s in inbound], orders)
        revised = [(s.qty, s.arrives_in_days) for s in revised_shipments]
        rows = allocate(on_hand, [(s["qty"], s["arrives_in_days"]) for s in others] + revised, orders)

        result = {
            "part_id": part_id,
            "po_number": po["po_number"],
            "current_shipment": {"qty": po["qty"], "arrives_in_days": po["arrives_in_days"]},
            "revised_shipments": [{"qty": q, "arrives_in_days": d} for q, d in revised],
            "revised_total": sum(q for q, _ in revised),
            "on_hand": on_hand,
            "other_shipments": others,
            "allocation_rule": ALLOCATION_RULE,
            "orders": rows,
            "orders_at_risk": [r["order_id"] for r in rows if r["at_risk"]],
            "already_at_risk_on_current_schedule": [r["order_id"] for r in current if r["at_risk"]],
        }
        return json.dumps(result, indent=1)

    return server


def resolve_company(value):
    """The company folder: the path as given, or else a folder of that name in week-05."""
    path = Path(value).expanduser()
    if not path.is_dir() and not path.is_absolute() and (WEEK_DIR / path).is_dir():
        path = WEEK_DIR / path
    return path.resolve()


def main():
    parser = argparse.ArgumentParser(description="MCP server with a company's supply data tools.")
    parser.add_argument(
        "--org",
        "--company",
        dest="org",
        metavar="FOLDER",
        default=str(DEFAULT_COMPANY_DIR),
        help="company folder holding the four CSV files (default: week-05/brookfield-bikes)",
    )
    args = parser.parse_args()

    try:
        folder = resolve_company(args.org)
        if not folder.is_dir():
            raise SetupError(f"--org: folder not found: {args.org}")
        company = Company(folder)
        for name in FILES:
            if not (folder / name).is_file():
                raise SetupError(f"Data file not found: {folder / name}")
            _, columns = company.read_with_columns(name)  # checks the columns now, so a bad file stops the server early
            if columns:
                log(f"{name}: " + ", ".join(f"{role} = {header}" for role, header in columns.items()))
        server = build_server(company)
    except (SetupError, ToolError) as error:
        log(f"Error: {error}")
        return 1

    log(f"{folder.name} supply MCP server running.")
    server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
