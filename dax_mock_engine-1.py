"""
dax_mock_engine.py  (v2 - expanded coverage)

Table-agnostic DAX interpreter. Runs a broad subset of real DAX syntax
against local pandas DataFrames, keyed by table name — so any number of
mock "reports" (Sales, Service Tickets, Order/Invoice, etc.) can be
queried through the exact same DAX strings you'd eventually send to
Power BI's executeQueries endpoint.

Output shape matches the real API: {"results": [{"tables": [{"rows": [...]}]}]}
so swapping this for _real_get_dataset later needs zero upstream changes.

v2 additions over v1:
  - Comparison operators: =, <>, >, <, >=, <=  (not just equality)
  - Date-range filters (compares as real dates, not strings)
  - Multi-condition filters joined with && (AND) / || (OR)
  - Filtering on ANY column (IDs, ticket numbers, order numbers, dates),
    not just short category-style columns
  - Multi-column SUMMARIZE (group by 2 columns, e.g. Region + Month)
  - More aggregations: AVERAGE, MIN, MAX, DISTINCTCOUNT
  - FILTER(Table, condition) as an alternative to CALCULATETABLE
  - Clearer error messages (DaxUnsupportedError vs DaxSyntaxError) so the
    app layer can tell "bad DAX" apart from "valid DAX we don't support yet"
"""

import re
import random
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)  # reproducible sample data across runs

# ---------------------------------------------------------------------------
# TABLE 1: SalesTransactions (existing)
# ---------------------------------------------------------------------------
SALES_TRANSACTIONS = pd.DataFrame([
    {"Date": "2025-01-03", "Region": "North", "Product": "Widget A", "Category": "Hardware", "Salesperson": "Alice", "Units": 10, "UnitPrice": 25.0, "Revenue": 250.0},
    {"Date": "2025-01-05", "Region": "South", "Product": "Widget B", "Category": "Hardware", "Salesperson": "Bob",   "Units": 5,  "UnitPrice": 40.0, "Revenue": 200.0},
    {"Date": "2025-01-07", "Region": "East",  "Product": "Widget A", "Category": "Hardware", "Salesperson": "Carol", "Units": 8,  "UnitPrice": 25.0, "Revenue": 200.0},
    {"Date": "2025-01-10", "Region": "West",  "Product": "Widget C", "Category": "Software", "Salesperson": "Dave",  "Units": 3,  "UnitPrice": 100.0,"Revenue": 300.0},
    {"Date": "2025-01-12", "Region": "North", "Product": "Widget B", "Category": "Hardware", "Salesperson": "Alice", "Units": 6,  "UnitPrice": 40.0, "Revenue": 240.0},
    {"Date": "2025-01-15", "Region": "South", "Product": "Widget C", "Category": "Software", "Salesperson": "Bob",   "Units": 4,  "UnitPrice": 100.0,"Revenue": 400.0},
    {"Date": "2025-01-18", "Region": "East",  "Product": "Widget A", "Category": "Hardware", "Salesperson": "Carol", "Units": 12, "UnitPrice": 25.0, "Revenue": 300.0},
    {"Date": "2025-01-20", "Region": "West",  "Product": "Widget B", "Category": "Hardware", "Salesperson": "Dave",  "Units": 7,  "UnitPrice": 40.0, "Revenue": 280.0},
    {"Date": "2025-01-22", "Region": "North", "Product": "Widget C", "Category": "Software", "Salesperson": "Alice", "Units": 2,  "UnitPrice": 100.0,"Revenue": 200.0},
    {"Date": "2025-01-25", "Region": "South", "Product": "Widget A", "Category": "Hardware", "Salesperson": "Bob",   "Units": 9,  "UnitPrice": 25.0, "Revenue": 225.0},
    {"Date": "2025-01-27", "Region": "East",  "Product": "Widget B", "Category": "Hardware", "Salesperson": "Carol", "Units": 5,  "UnitPrice": 40.0, "Revenue": 200.0},
    {"Date": "2025-01-29", "Region": "West",  "Product": "Widget A", "Category": "Hardware", "Salesperson": "Dave",  "Units": 11, "UnitPrice": 25.0, "Revenue": 275.0},
    {"Date": "2025-02-02", "Region": "North", "Product": "Widget B", "Category": "Hardware", "Salesperson": "Alice", "Units": 6,  "UnitPrice": 40.0, "Revenue": 240.0},
    {"Date": "2025-02-05", "Region": "South", "Product": "Widget C", "Category": "Software", "Salesperson": "Bob",   "Units": 5,  "UnitPrice": 100.0,"Revenue": 500.0},
    {"Date": "2025-02-08", "Region": "East",  "Product": "Widget A", "Category": "Hardware", "Salesperson": "Carol", "Units": 10, "UnitPrice": 25.0, "Revenue": 250.0},
])

# ---------------------------------------------------------------------------
# TABLE 2: ServiceCentralTickets (new)
# Columns: TicketNumber, Status(Open/Closed), CreatedBy, RequestedBy,
#          CreatedDate, ClosedDate, Category, Priority
# ---------------------------------------------------------------------------
def _generate_tickets(n=250):
    agents = ["Alice", "Bob", "Carol", "Dave", "Emma", "Frank"]
    requesters = ["Nina", "Omar", "Priya", "Liam", "Sara", "Tom", "Zoe", "Kevin"]
    categories = ["Hardware", "Software", "Network", "Access Request", "Bug"]
    priorities = ["Low", "Medium", "High", "Critical"]
    base_date = datetime(2025, 1, 1)

    rows = []
    for i in range(1, n + 1):
        created = base_date + timedelta(days=random.randint(0, 364))
        is_closed = random.random() < 0.65
        closed = created + timedelta(days=random.randint(1, 14)) if is_closed else None
        rows.append({
            "TicketNumber": f"TCK-{1000 + i}",
            "Status": "Closed" if is_closed else "Open",
            "CreatedBy": random.choice(agents),
            "RequestedBy": random.choice(requesters),
            "CreatedDate": created.strftime("%Y-%m-%d"),
            "ClosedDate": closed.strftime("%Y-%m-%d") if closed else None,
            "Category": random.choice(categories),
            "Priority": random.choice(priorities),
        })
    return pd.DataFrame(rows)

SERVICE_CENTRAL_TICKETS = _generate_tickets(250)

# ---------------------------------------------------------------------------
# TABLE 3: OrderInvoiceProcessing (new)
# Columns: OrderID, OrderDate, InvoiceID, InvoiceDate, BillingAmount,
#          Vendor, VendorPaymentStatus(Paid/Unpaid)
# ---------------------------------------------------------------------------
def _generate_orders(n=180):
    vendors = ["Acme Supplies", "Globex Corp", "Initech", "Umbrella Logistics", "Stark Materials"]
    base_date = datetime(2025, 1, 1)

    rows = []
    for i in range(1, n + 1):
        order_date = base_date + timedelta(days=random.randint(0, 364))
        invoice_date = order_date + timedelta(days=random.randint(1, 5))
        rows.append({
            "OrderID": f"ORD-{5000 + i}",
            "OrderDate": order_date.strftime("%Y-%m-%d"),
            "InvoiceID": f"INV-{7000 + i}",
            "InvoiceDate": invoice_date.strftime("%Y-%m-%d"),
            "BillingAmount": round(random.uniform(150, 5000), 2),
            "Vendor": random.choice(vendors),
            "VendorPaymentStatus": random.choice(["Paid", "Unpaid"]),
        })
    return pd.DataFrame(rows)

ORDER_INVOICE_PROCESSING = _generate_orders(180)

# ---------------------------------------------------------------------------
# Table registry — maps DAX table name -> DataFrame
# ---------------------------------------------------------------------------
TABLES = {
    "SalesTransactions": SALES_TRANSACTIONS,
    "ServiceCentralTickets": SERVICE_CENTRAL_TICKETS,
    "OrderInvoiceProcessing": ORDER_INVOICE_PROCESSING,
}

# Columns that hold real calendar dates, per table — used so filters and
# comparisons on these columns are done as actual dates, not strings.
DATE_COLUMNS = {
    "SalesTransactions": {"Date"},
    "ServiceCentralTickets": {"CreatedDate", "ClosedDate"},
    "OrderInvoiceProcessing": {"OrderDate", "InvoiceDate"},
}

# ---------------------------------------------------------------------------
# Report registry — mirrors what _real_get_reports() would return from
# Power BI: each "report" maps to one dataset/table.
# ---------------------------------------------------------------------------
REPORTS_REGISTRY = {
    "report-sales-001": {"name": "Sales Overview", "table": "SalesTransactions"},
    "report-tickets-002": {"name": "Service Central Tickets", "table": "ServiceCentralTickets"},
    "report-orders-003": {"name": "Order & Invoice Processing", "table": "OrderInvoiceProcessing"},
}


class DaxSyntaxError(Exception):
    """The DAX text itself is malformed (unbalanced parens, bad ROW(), etc.)."""
    pass


class DaxUnsupportedError(Exception):
    """The DAX is well-formed but uses a pattern this mock engine doesn't
    implement yet (e.g. a function we haven't built). Kept separate from
    DaxSyntaxError so the app layer can show a clear, honest message
    instead of implying a data-access problem."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_balanced(s: str, start: int) -> str:
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return s[start + 1:i]
    raise DaxSyntaxError("Unbalanced parentheses in DAX query")


def _detect_table_name(query: str) -> str:
    """Find the first Table[Column] reference and match it against the
    registry. Falls back to scanning for a bare table name mention."""
    m = re.search(r"(\w+)\[\w+\]", query)
    if m and m.group(1) in TABLES:
        return m.group(1)
    for name in TABLES:
        if re.search(rf"\b{name}\b", query):
            return name
    raise DaxSyntaxError("Could not detect table name in DAX query — "
                          f"expected one of {list(TABLES.keys())}")


def _col(table_name: str, ref: str) -> str:
    m = re.match(rf"{table_name}\[(.+)\]", ref.strip())
    return m.group(1) if m else ref.strip()


def _coerce(df: pd.DataFrame, table_name: str, col: str, raw_val: str):
    """Turn a quoted literal into the right Python type for comparison:
    a real date if the column is a known date column, a number if the
    column is numeric, else the raw string."""
    if col in DATE_COLUMNS.get(table_name, set()):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw_val, fmt)
            except ValueError:
                continue
        return raw_val  # couldn't parse as a date; fall back to string compare

    if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
        try:
            return float(raw_val)
        except ValueError:
            return raw_val  # not actually numeric text; fall back to string compare

    return raw_val


def _series_for_compare(df: pd.DataFrame, table_name: str, col: str):
    if col in DATE_COLUMNS.get(table_name, set()):
        return pd.to_datetime(df[col], errors="coerce")
    return df[col]


_OPS = {
    "<>": lambda s, v: s != v,
    ">=": lambda s, v: s >= v,
    "<=": lambda s, v: s <= v,
    ">":  lambda s, v: s > v,
    "<":  lambda s, v: s < v,
    "=":  lambda s, v: s == v,
}
# Order matters: check 2-char operators before the 1-char ones.
_OP_PATTERN = r"(<>|>=|<=|>|<|=)"


def _apply_single_condition(df: pd.DataFrame, table_name: str, condition: str) -> pd.DataFrame:
    condition = condition.strip().strip("()")
    m = re.match(
        rf'{table_name}\[(\w+)\]\s*{_OP_PATTERN}\s*"?([^"]+?)"?\s*$',
        condition,
    )
    if not m:
        raise DaxUnsupportedError(
            f"Filter condition not recognized by mock engine: {condition!r}. "
            "Supported form: Table[Column] <op> \"value\", where <op> is one of = <> > < >= <=."
        )
    col, op, raw_val = m.group(1), m.group(2), m.group(3)
    if col not in df.columns:
        raise DaxUnsupportedError(f"Column '{col}' does not exist on table '{table_name}'.")

    series = _series_for_compare(df, table_name, col)
    val = _coerce(df, table_name, col, raw_val)
    if col in DATE_COLUMNS.get(table_name, set()) and isinstance(val, str):
        raise DaxUnsupportedError(f"Could not parse date value '{raw_val}' for column '{col}'.")

    mask = _OPS[op](series, val)
    return df[mask]


def _apply_filter(df: pd.DataFrame, table_name: str, condition: str) -> pd.DataFrame:
    """Supports a single condition, or multiple conditions joined by && (AND)
    or || (OR). Example:
    ServiceCentralTickets[Status]="Open" && ServiceCentralTickets[Priority]="High"
    """
    condition = condition.strip()

    if "&&" in condition:
        parts = condition.split("&&")
        result = df
        for part in parts:
            result = _apply_single_condition(result, table_name, part)
        return result

    if "||" in condition:
        parts = condition.split("||")
        masks = [
            _apply_single_condition(df, table_name, part).index
            for part in parts
        ]
        combined_index = masks[0]
        for idx in masks[1:]:
            combined_index = combined_index.union(idx)
        return df.loc[combined_index].sort_index()

    return _apply_single_condition(df, table_name, condition)


def _eval_agg(df: pd.DataFrame, table_name: str, expr: str):
    """Dispatch to SUM/COUNT/COUNTROWS/AVERAGE/MIN/MAX/DISTINCTCOUNT."""
    expr = expr.strip()
    upper = expr.upper()

    def _single_col_call(fn_name):
        m = re.match(rf"{fn_name}\({table_name}\[(\w+)\]\)$", expr, flags=re.IGNORECASE)
        if not m:
            raise DaxUnsupportedError(f"Unsupported {fn_name} expression: {expr}")
        return m.group(1)

    if upper.startswith("SUM("):
        col = _single_col_call("SUM")
        return float(df[col].sum())

    if upper.startswith("AVERAGE("):
        col = _single_col_call("AVERAGE")
        return float(df[col].mean()) if len(df) else 0.0

    if upper.startswith("MIN("):
        col = _single_col_call("MIN")
        return df[col].min()

    if upper.startswith("MAX("):
        col = _single_col_call("MAX")
        return df[col].max()

    if upper.startswith("DISTINCTCOUNT("):
        col = _single_col_call("DISTINCTCOUNT")
        return int(df[col].nunique())

    if upper.startswith("COUNTROWS("):
        m = re.match(rf"COUNTROWS\({table_name}\)$", expr, flags=re.IGNORECASE)
        if m:
            return len(df)
        m = re.match(r"COUNTROWS\(\s*(CALCULATETABLE|FILTER)\(", expr, flags=re.IGNORECASE)
        if m:
            fn = m.group(1)
            inner = _extract_balanced(expr, expr.index(fn) + len(fn))
            parts = inner.split(",", 1)
            condition = parts[1] if len(parts) > 1 else None
            filtered = _apply_filter(df, table_name, condition) if condition else df
            return len(filtered)
        raise DaxUnsupportedError(f"Unsupported COUNTROWS expression: {expr}")

    if upper.startswith("COUNT("):
        col = _single_col_call("COUNT")
        return int(df[col].count())

    raise DaxUnsupportedError(f"Unsupported aggregation function in: {expr}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_dax(query: str) -> dict:
    """
    Execute a DAX query string against the appropriate registered table
    (auto-detected from the query text). Returns the same shape as
    Power BI's executeQueries response.
    """
    q = query.strip()
    q = re.sub(r"^EVALUATE\s+", "", q, flags=re.IGNORECASE)

    table_name = _detect_table_name(q)
    df = TABLES[table_name].copy()

    # --- ROW("Label", AGG(...)) or ROW("L1", AGG1, "L2", AGG2, ...) ---
    if q.upper().startswith("ROW"):
        inner = _extract_balanced(q, q.index("("))
        parts = [p.strip() for p in re.split(r",(?![^()]*\))", inner)]
        if len(parts) % 2 != 0:
            raise DaxSyntaxError("Malformed ROW() expression — labels and expressions must pair up")
        row = {}
        for i in range(0, len(parts), 2):
            label = parts[i].strip('"')
            expr = parts[i + 1]
            row[label] = _eval_agg(df, table_name, expr)
        return {"results": [{"tables": [{"rows": [row]}]}]}

    # --- CALCULATETABLE(Table, condition[, condition2, ...]) -> filtered rows ---
    if q.upper().startswith("CALCULATETABLE"):
        inner = _extract_balanced(q, q.index("("))
        parts = [p.strip() for p in re.split(r",(?![^()]*\))", inner)]
        conditions = parts[1:] if len(parts) > 1 else []
        result_df = df
        for condition in conditions:
            result_df = _apply_filter(result_df, table_name, condition)
        rows = result_df.to_dict(orient="records")
        return {"results": [{"tables": [{"rows": rows}]}]}

    # --- FILTER(Table, condition) -> filtered rows (alt. to CALCULATETABLE) ---
    if q.upper().startswith("FILTER("):
        inner = _extract_balanced(q, q.index("("))
        parts = inner.split(",", 1)
        condition = parts[1] if len(parts) > 1 else None
        result_df = _apply_filter(df, table_name, condition) if condition else df
        rows = result_df.to_dict(orient="records")
        return {"results": [{"tables": [{"rows": rows}]}]}

    # --- SUMMARIZE(Table, GroupCol[, GroupCol2], "Label", AGG(...)) / TOPN(...) ---
    if q.upper().startswith("SUMMARIZE") or q.upper().startswith("TOPN(") or "SUMMARIZE(" in q.upper():
        topn_limit, topn_sort_desc = None, True
        if q.upper().startswith("TOPN"):
            inner = _extract_balanced(q, q.index("("))
            n_match = re.match(r"\s*(\d+)\s*,\s*(.+)", inner)
            topn_limit = int(n_match.group(1))
            rest = n_match.group(2)
            sm_idx = rest.upper().index("SUMMARIZE")
            summarize_inner = _extract_balanced(rest, rest.index("(", sm_idx))
            after = rest[rest.index("(", sm_idx) + len(summarize_inner) + 2:]
            topn_sort_desc = "DESC" in after.upper()
        else:
            summarize_inner = _extract_balanced(q, q.index("("))

        args = [a.strip() for a in re.split(r",(?![^()]*\))", summarize_inner)]

        # args[0] is the table. Everything up to the first quoted string is a
        # group-by column; the rest alternate "Label", AGG(...).
        group_cols = []
        idx = 1
        while idx < len(args) and not args[idx].startswith('"'):
            group_cols.append(_col(table_name, args[idx]))
            idx += 1

        if not group_cols:
            raise DaxSyntaxError("SUMMARIZE requires at least one group-by column")

        label_agg_pairs = args[idx:]
        if len(label_agg_pairs) < 2 or len(label_agg_pairs) % 2 != 0:
            raise DaxSyntaxError('SUMMARIZE requires "Label", AGG(...) pairs after the group columns')

        label = label_agg_pairs[0].strip('"')
        agg_expr = label_agg_pairs[1]
        # (Extra label/agg pairs beyond the first are accepted but only the
        # first is used for TOPN sorting — matches the common real-world case
        # of one metric per chart.)

        grouped = (
            df.groupby(group_cols)
            .apply(lambda g: _eval_agg(g, table_name, agg_expr))
            .reset_index()
        )
        grouped.columns = list(group_cols) + [label]

        if topn_limit:
            grouped = grouped.sort_values(label, ascending=not topn_sort_desc).head(topn_limit)

        rows = grouped.to_dict(orient="records")
        return {"results": [{"tables": [{"rows": rows}]}]}

    raise DaxUnsupportedError(f"Query pattern not supported by mock engine: {q[:80]}...")


if __name__ == "__main__":
    tests = [
        # Basic aggregation (v1, still works)
        'EVALUATE ROW("Total Revenue", SUM(SalesTransactions[Revenue]))',

        # Multi-metric ROW
        'EVALUATE ROW("Total Revenue", SUM(SalesTransactions[Revenue]), "Avg Revenue", AVERAGE(SalesTransactions[Revenue]))',

        # Single condition (v1, still works)
        'EVALUATE ROW("Open Tickets", COUNTROWS(CALCULATETABLE(ServiceCentralTickets, ServiceCentralTickets[Status] = "Open")))',

        # NEW: multi-condition AND filter
        'EVALUATE CALCULATETABLE(ServiceCentralTickets, ServiceCentralTickets[Status] = "Open" && ServiceCentralTickets[Priority] = "High")',

        # NEW: date range filter (>=, <=)
        'EVALUATE CALCULATETABLE(OrderInvoiceProcessing, OrderInvoiceProcessing[OrderDate] >= "2025-03-01" && OrderInvoiceProcessing[OrderDate] <= "2025-06-30")',

        # NEW: filter by exact ID (previously failed as "not a category column")
        'EVALUATE CALCULATETABLE(OrderInvoiceProcessing, OrderInvoiceProcessing[OrderID] = "ORD-5012")',
        'EVALUATE CALCULATETABLE(ServiceCentralTickets, ServiceCentralTickets[TicketNumber] = "TCK-1005")',

        # NEW: FILTER() as an alternative wrapper
        'EVALUATE FILTER(ServiceCentralTickets, ServiceCentralTickets[Priority] = "Critical")',

        # NEW: multi-column grouping (Region + Product) for richer charts
        'EVALUATE SUMMARIZE(SalesTransactions, SalesTransactions[Region], SalesTransactions[Product], "TotalRevenue", SUM(SalesTransactions[Revenue]))',

        # Existing single-column grouping (v1, still works)
        'EVALUATE SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[Priority], "TicketCount", COUNTROWS(ServiceCentralTickets))',

        # NEW: DISTINCTCOUNT
        'EVALUATE ROW("Unique Vendors", DISTINCTCOUNT(OrderInvoiceProcessing[Vendor]))',

        # TOPN (v1, still works)
        'EVALUATE TOPN(3, SUMMARIZE(OrderInvoiceProcessing, OrderInvoiceProcessing[Vendor], "TotalBilled", SUM(OrderInvoiceProcessing[BillingAmount])), [TotalBilled], DESC)',

        # NEW: an intentionally unsupported pattern, to show the clearer error
        'EVALUATE ADDCOLUMNS(SalesTransactions, "Margin", SalesTransactions[Revenue] - 100)',
    ]
    for t in tests:
        print("\nDAX:", t)
        try:
            result = run_dax(t)
            rows = result["results"][0]["tables"][0]["rows"]
            print(f"Result: {len(rows)} row(s) ->", rows[:3], "..." if len(rows) > 3 else "")
        except (DaxSyntaxError, DaxUnsupportedError) as e:
            print(f"{type(e).__name__}:", e)
