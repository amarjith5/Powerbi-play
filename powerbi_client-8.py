"""
Power BI Client — Mock mode now, Real API swap later.
To switch to real PBI: set POWERBI_MODE=real in .env
and fill in POWERBI_CLIENT_ID, POWERBI_CLIENT_SECRET, POWERBI_TENANT_ID

Two additional reports (Service Central Tickets, Order & Invoice Processing)
are backed by dax_mock_engine.py — their metrics dicts are assembled by
running real DAX query strings against local sample tables, so you can
learn/demo actual DAX querying before real Power BI credentials arrive.
When POWERBI_MODE=real, these two reports simply won't appear (real mode
only returns whatever the org's actual workspace has).
"""
import os
import re
from datetime import datetime, timedelta
from models import ReportMeta, DatasetSummary
from dax_mock_engine import run_dax, DaxSyntaxError, TABLES

MOCK_REPORTS = [
    ReportMeta(id="rpt-001", name="Sales Overview Dashboard", workspace="Sales Team", description="Monthly and quarterly sales KPIs, regional breakdown, top products"),
    ReportMeta(id="rpt-002", name="Revenue vs Target", workspace="Sales Team", description="Actual revenue vs targets by region and product category"),
    ReportMeta(id="rpt-003", name="Customer Acquisition Report", workspace="Marketing", description="New customers, churn rate, acquisition cost by channel"),
    ReportMeta(id="rpt-004", name="Product Performance", workspace="Sales Team", description="Units sold, revenue, margin by product line"),
]

MOCK_DATA = {
    "rpt-001": {
        "total_revenue": 4820000,
        "revenue_growth": 12.4,
        "total_orders": 18430,
        "avg_order_value": 261.5,
        "top_regions": {"North": 1420000, "South": 980000, "East": 1250000, "West": 1170000},
        "monthly_revenue": {
            "Jan": 380000, "Feb": 395000, "Mar": 410000,
            "Apr": 425000, "May": 398000, "Jun": 440000,
            "Jul": 415000, "Aug": 460000, "Sep": 478000,
            "Oct": 502000, "Nov": 490000, "Dec": 427000,
        },
        "top_products": {"Enterprise Suite": 1200000, "Pro License": 980000, "Starter Pack": 640000, "Add-ons": 420000, "Support": 380000},
        "target_vs_actual": {"Q1": {"target": 1100000, "actual": 1185000}, "Q2": {"target": 1200000, "actual": 1263000}, "Q3": {"target": 1300000, "actual": 1353000}, "Q4": {"target": 1400000, "actual": 1419000}},
    },
    "rpt-002": {
        "revenue_achievement_pct": 103.2,
        "regions_above_target": ["North", "East", "West"],
        "regions_below_target": ["South"],
        "best_quarter": "Q3",
        "gap_analysis": {"North": +8.2, "South": -4.1, "East": +6.7, "West": +5.3},
    },
    "rpt-003": {
        "new_customers": 2840,
        "churn_rate": 3.2,
        "customer_acquisition_cost": 184,
        "lifetime_value": 2400,
        "channels": {"Organic": 820, "Paid Search": 640, "Referral": 580, "Social": 420, "Direct": 380},
    },
    "rpt-004": {
        "total_units_sold": 12400,
        "best_selling_product": "Enterprise Suite",
        "highest_margin_product": "Add-ons",
        "products": {
            "Enterprise Suite": {"units": 3200, "revenue": 1200000, "margin_pct": 68},
            "Pro License": {"units": 4100, "revenue": 980000, "margin_pct": 72},
            "Starter Pack": {"units": 3800, "revenue": 640000, "margin_pct": 61},
            "Add-ons": {"units": 900, "revenue": 420000, "margin_pct": 84},
            "Support": {"units": 400, "revenue": 380000, "margin_pct": 55},
        },
    },
}

# ── New DAX-backed reports ─────────────────────────────────────────────────
DAX_REPORTS = [
    ReportMeta(id="rpt-005", name="Service Central Tickets", workspace="IT Service Desk", description="Open/closed ticket volumes, requester and agent breakdown, priority and category mix"),
    ReportMeta(id="rpt-006", name="Order & Invoice Processing", workspace="Finance / Procurement", description="Order and invoice volumes, billing totals, vendor payment status"),
]

# Maps DAX-backed report id -> table name in dax_mock_engine.py
DAX_TABLE_MAP = {
    "rpt-005": "ServiceCentralTickets",
    "rpt-006": "OrderInvoiceProcessing",
}


def _rows_to_dict(rows: list[dict], key_field: str, value_field: str) -> dict:
    """Turn DAX SUMMARIZE result rows into a simple {group: value} dict,
    matching the shape used throughout MOCK_DATA (e.g. top_regions)."""
    return {r[key_field]: r[value_field] for r in rows}


def _run(dax: str):
    """Execute a DAX string and return its rows list, raising DaxSyntaxError
    on failure (caller decides how to handle it)."""
    result = run_dax(dax)
    return result["results"][0]["tables"][0]["rows"]


def _build_ticket_metrics() -> dict:
    total = _run('EVALUATE ROW("Total", COUNTROWS(ServiceCentralTickets))')[0]["Total"]
    open_count = _run(
        'EVALUATE ROW("Open", COUNTROWS(CALCULATETABLE(ServiceCentralTickets, ServiceCentralTickets[Status] = "Open")))'
    )[0]["Open"]
    closed_count = total - open_count

    by_status = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[Status], "Count", COUNTROWS(ServiceCentralTickets))'),
        "Status", "Count",
    )
    by_priority = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[Priority], "Count", COUNTROWS(ServiceCentralTickets))'),
        "Priority", "Count",
    )
    by_category = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[Category], "Count", COUNTROWS(ServiceCentralTickets))'),
        "Category", "Count",
    )
    by_requester = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[RequestedBy], "Count", COUNTROWS(ServiceCentralTickets))'),
        "RequestedBy", "Count",
    )
    top_agent_rows = _run(
        'EVALUATE TOPN(1, SUMMARIZE(ServiceCentralTickets, ServiceCentralTickets[CreatedBy], "Count", COUNTROWS(ServiceCentralTickets)), [Count], DESC)'
    )
    top_agent = top_agent_rows[0]["CreatedBy"] if top_agent_rows else None

    # Cross-tab: status x priority (fixes "open AND high priority" style
    # questions the flat by_status/by_priority breakdowns can't answer)
    df_all = TABLES["ServiceCentralTickets"]
    status_priority_crosstab = (
        df_all.groupby(["Status", "Priority"]).size().unstack(fill_value=0).to_dict()
    )
    # Reshape to {status: {priority: count}} for easier LLM consumption
    open_by_priority = {
        priority: int(counts.get("Open", 0))
        for priority, counts in status_priority_crosstab.items()
    }
    closed_by_priority = {
        priority: int(counts.get("Closed", 0))
        for priority, counts in status_priority_crosstab.items()
    }

    # Monthly created-ticket trend (fixes "tickets created between X and Y" /
    # "volume by month" style questions)
    df_dates = df_all.copy()
    df_dates["_month"] = df_dates["CreatedDate"].str.slice(0, 7)  # "YYYY-MM"
    tickets_by_month = df_dates.groupby("_month").size().sort_index().to_dict()

    # Average resolution time isn't expressible with the mock engine's DAX
    # subset (no date-diff function yet), so it's computed directly from the
    # same underlying table for now — everything else above is real DAX.
    df = TABLES["ServiceCentralTickets"]
    closed_df = df[df["Status"] == "Closed"].copy()
    closed_df["_created"] = closed_df["CreatedDate"].apply(lambda d: datetime.strptime(d, "%Y-%m-%d"))
    closed_df["_closed"] = closed_df["ClosedDate"].apply(lambda d: datetime.strptime(d, "%Y-%m-%d"))
    avg_days = (closed_df["_closed"] - closed_df["_created"]).dt.days.mean() if len(closed_df) else 0

    return {
        "total_tickets": total,
        "open_tickets": open_count,
        "closed_tickets": closed_count,
        "tickets_by_status": by_status,
        "tickets_by_priority": by_priority,
        "tickets_by_category": by_category,
        "tickets_by_requester": by_requester,
        "open_tickets_by_priority": open_by_priority,
        "closed_tickets_by_priority": closed_by_priority,
        "tickets_created_by_month": tickets_by_month,
        "top_agent_by_volume": top_agent,
        "avg_resolution_days": round(float(avg_days), 1) if avg_days else None,
    }


def _build_order_metrics() -> dict:
    total_orders = _run('EVALUATE ROW("Total", COUNTROWS(OrderInvoiceProcessing))')[0]["Total"]
    total_billed = _run('EVALUATE ROW("Total", SUM(OrderInvoiceProcessing[BillingAmount]))')[0]["Total"]

    # Filtered SUM isn't directly expressible in the mock engine's DAX subset
    # (no SUMX/CALCULATE(SUM(...), filter) combo yet), so we pull the filtered
    # rows via real DAX (CALCULATETABLE) and total them in Python.
    paid_rows = _run('EVALUATE CALCULATETABLE(OrderInvoiceProcessing, OrderInvoiceProcessing[VendorPaymentStatus] = "Paid")')
    unpaid_rows = _run('EVALUATE CALCULATETABLE(OrderInvoiceProcessing, OrderInvoiceProcessing[VendorPaymentStatus] = "Unpaid")')
    paid_amount = round(sum(r["BillingAmount"] for r in paid_rows), 2)
    unpaid_amount = round(sum(r["BillingAmount"] for r in unpaid_rows), 2)

    by_payment_status = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(OrderInvoiceProcessing, OrderInvoiceProcessing[VendorPaymentStatus], "Count", COUNTROWS(OrderInvoiceProcessing))'),
        "VendorPaymentStatus", "Count",
    )
    billing_by_vendor = _rows_to_dict(
        _run('EVALUATE SUMMARIZE(OrderInvoiceProcessing, OrderInvoiceProcessing[Vendor], "Total", SUM(OrderInvoiceProcessing[BillingAmount]))'),
        "Vendor", "Total",
    )
    top_vendor_rows = _run(
        'EVALUATE TOPN(1, SUMMARIZE(OrderInvoiceProcessing, OrderInvoiceProcessing[Vendor], "Total", SUM(OrderInvoiceProcessing[BillingAmount])), [Total], DESC)'
    )
    top_vendor = top_vendor_rows[0]["Vendor"] if top_vendor_rows else None

    # Unpaid-specific per-vendor breakdown, computed from the REAL filtered
    # rows (not a proportional guess against total billing). This directly
    # fixes the "which vendor has the most unpaid invoices" bug, where the
    # app previously fabricated a distribution instead of counting actual
    # unpaid records per vendor.
    unpaid_df = TABLES["OrderInvoiceProcessing"]
    unpaid_df = unpaid_df[unpaid_df["VendorPaymentStatus"] == "Unpaid"]
    unpaid_count_by_vendor = unpaid_df.groupby("Vendor").size().to_dict()
    unpaid_amount_by_vendor = unpaid_df.groupby("Vendor")["BillingAmount"].sum().round(2).to_dict()
    top_unpaid_vendor = (
        max(unpaid_count_by_vendor, key=unpaid_count_by_vendor.get)
        if unpaid_count_by_vendor else None
    )

    # Oldest outstanding (unpaid) invoice
    oldest_unpaid = None
    if len(unpaid_df):
        oldest_row = unpaid_df.loc[unpaid_df["OrderDate"].idxmin()]
        oldest_unpaid = {
            "OrderID": oldest_row["OrderID"],
            "InvoiceID": oldest_row["InvoiceID"],
            "Vendor": oldest_row["Vendor"],
            "OrderDate": oldest_row["OrderDate"],
            "BillingAmount": float(oldest_row["BillingAmount"]),
        }

    return {
        "total_orders": total_orders,
        "total_billing_amount": round(total_billed, 2),
        "paid_amount": paid_amount,
        "unpaid_amount": unpaid_amount,
        "orders_by_payment_status": by_payment_status,
        "billing_by_vendor": billing_by_vendor,
        "unpaid_invoice_count_by_vendor": {k: int(v) for k, v in unpaid_count_by_vendor.items()},
        "unpaid_amount_by_vendor": unpaid_amount_by_vendor,
        "top_vendor_by_unpaid_count": top_unpaid_vendor,
        "top_vendor_by_billing": top_vendor,
        "oldest_unpaid_invoice": oldest_unpaid,
        "avg_invoice_amount": round(total_billed / total_orders, 2) if total_orders else 0,
    }


def _natural_sort_key(value: str):
    """
    Sort key for IDs like 'TCK-1042' or 'ORD-5012': extracts the trailing
    number so ordering is numeric ('TCK-2' before 'TCK-10'), not a plain
    string sort (which would wrongly put 'TCK-10' before 'TCK-2').
    """
    match = re.search(r"(\d+)\s*$", str(value))
    return int(match.group(1)) if match else str(value)


def _sort_rows_by(rows: list[dict], field: str) -> list[dict]:
    if not rows or field not in rows[0]:
        return rows
    return sorted(rows, key=lambda r: _natural_sort_key(r.get(field, "")))


def query_tickets(
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    created_by: str | None = None,
    requested_by: str | None = None,
    ticket_number: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 300,
) -> list[dict]:
    """
    Run a live, filtered query against ServiceCentralTickets and return the
    matching rows as-is (full record: TicketNumber, Status, dates, etc.).

    Unlike the fixed metrics dict built once at report-load time, this runs
    fresh against the real table every call — so it correctly answers
    questions the static summary can't, such as:
      - "open, high priority tickets created by Bob"
      - "tickets created between March and June"
      - "show me ticket TCK-1042"
    All filters are ANDed together; any left as None is not applied.
    date_from/date_to filter on CreatedDate (inclusive), format "YYYY-MM-DD".
    """
    conditions = []
    if status:
        conditions.append(f'ServiceCentralTickets[Status] = "{status}"')
    if priority:
        conditions.append(f'ServiceCentralTickets[Priority] = "{priority}"')
    if category:
        conditions.append(f'ServiceCentralTickets[Category] = "{category}"')
    if created_by:
        conditions.append(f'ServiceCentralTickets[CreatedBy] = "{created_by}"')
    if requested_by:
        conditions.append(f'ServiceCentralTickets[RequestedBy] = "{requested_by}"')
    if ticket_number:
        conditions.append(f'ServiceCentralTickets[TicketNumber] = "{ticket_number}"')
    if date_from:
        conditions.append(f'ServiceCentralTickets[CreatedDate] >= "{date_from}"')
    if date_to:
        conditions.append(f'ServiceCentralTickets[CreatedDate] <= "{date_to}"')

    if conditions:
        dax = f'EVALUATE CALCULATETABLE(ServiceCentralTickets, {" && ".join(conditions)})'
    else:
        dax = 'EVALUATE ServiceCentralTickets'  # no filters -> full table (still capped by `limit` below)

    rows = _run(dax)
    rows = _sort_rows_by(rows, "TicketNumber")
    return rows[:limit]


def query_orders(
    order_id: str | None = None,
    invoice_id: str | None = None,
    vendor: str | None = None,
    payment_status: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 300,
) -> list[dict]:
    """
    Run a live, filtered query against OrderInvoiceProcessing and return the
    matching rows as-is. Same pattern as query_tickets — see that docstring.
    date_from/date_to filter on OrderDate (inclusive), format "YYYY-MM-DD".
    """
    conditions = []
    if order_id:
        conditions.append(f'OrderInvoiceProcessing[OrderID] = "{order_id}"')
    if invoice_id:
        conditions.append(f'OrderInvoiceProcessing[InvoiceID] = "{invoice_id}"')
    if vendor:
        conditions.append(f'OrderInvoiceProcessing[Vendor] = "{vendor}"')
    if payment_status:
        conditions.append(f'OrderInvoiceProcessing[VendorPaymentStatus] = "{payment_status}"')
    if min_amount is not None:
        conditions.append(f'OrderInvoiceProcessing[BillingAmount] >= "{min_amount}"')
    if max_amount is not None:
        conditions.append(f'OrderInvoiceProcessing[BillingAmount] <= "{max_amount}"')
    if date_from:
        conditions.append(f'OrderInvoiceProcessing[OrderDate] >= "{date_from}"')
    if date_to:
        conditions.append(f'OrderInvoiceProcessing[OrderDate] <= "{date_to}"')

    if conditions:
        dax = f'EVALUATE CALCULATETABLE(OrderInvoiceProcessing, {" && ".join(conditions)})'
    else:
        dax = 'EVALUATE OrderInvoiceProcessing'

    rows = _run(dax)
    rows = _sort_rows_by(rows, "OrderID")
    return rows[:limit]


class PowerBIClient:
    def __init__(self):
        self.mode = os.getenv("POWERBI_MODE", "mock")

    def get_reports(self) -> list[ReportMeta]:
        if self.mode == "real":
            return self._real_get_reports()
        # mock mode: original static reports + the two DAX-backed ones
        return MOCK_REPORTS + DAX_REPORTS

    def get_dataset(self, report_id: str) -> DatasetSummary:
        if self.mode == "real":
            return self._real_get_dataset(report_id)

        if report_id in DAX_TABLE_MAP:
            try:
                if report_id == "rpt-005":
                    metrics = _build_ticket_metrics()
                else:
                    metrics = _build_order_metrics()
            except DaxSyntaxError as e:
                metrics = {"error": str(e)}
            return DatasetSummary(
                report_id=report_id,
                metrics=metrics,
                last_refreshed=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )

        data = MOCK_DATA.get(report_id, {})
        return DatasetSummary(
            report_id=report_id,
            metrics=data,
            last_refreshed=(datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        )

    # ── Real API methods (fill in when org gives access) ──────────────────
    def _real_get_reports(self):
        """
        TODO: Replace with real Power BI REST API call
        import requests, msal
        app = msal.ConfidentialClientApplication(CLIENT_ID, CLIENT_SECRET, f"https://login.microsoftonline.com/{TENANT_ID}")
        token = app.acquire_token_for_client(["https://analysis.windows.net/powerbi/api/.default"])
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        r = requests.get("https://api.powerbi.com/v1.0/myorg/reports", headers=headers)
        return r.json()["value"]
        """
        raise NotImplementedError("Set POWERBI_MODE=mock until org API access is granted")

    def _real_get_dataset(self, report_id: str):
        raise NotImplementedError("Set POWERBI_MODE=mock until org API access is granted")
