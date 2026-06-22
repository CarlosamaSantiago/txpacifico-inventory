from pathlib import Path
import re
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
POWERBI_DATASET_DIR = PROJECT_ROOT / "reports" / "powerbi" / "dataset"


TOLERANCE = 0.01


REQUIRED_PROCESSED_FILES = [
    "opening_stock_movements.csv",
    "sales_stock_movements.csv",
    "receipt_stock_movements_raw.csv",
    "receipt_stock_movements.csv",
    "duplicate_lotrols.csv",
    "stock_movements.csv",
    "monthly_inventory_balance.csv",
    "current_inventory_balance.csv",
    "company_monthly_inventory_summary.csv",
]

REQUIRED_POWERBI_FILES = [
    "fact_stock_movements.csv",
    "fact_monthly_inventory_balance.csv",
    "fact_company_monthly_summary.csv",
    "fact_duplicate_lotrols.csv",
    "fact_inventory_exceptions.csv",
    "dim_product_variant.csv",
    "dim_month.csv",
]


def to_number(series: pd.Series) -> pd.Series:
    def clean_value(value):
        if pd.isna(value):
            return ""

        text = str(value).strip()
        text = text.replace("\ufeff", "")
        text = text.replace("\xa0", "")
        text = text.replace(" ", "")

        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]

        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text and "." not in text:
            text = text.replace(",", ".")

        text = re.sub(r"[^0-9.\-]", "", text)

        return text

    return pd.to_numeric(series.apply(clean_value), errors="coerce").fillna(0.0)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")

    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def almost_equal(left: float, right: float, tolerance: float = TOLERANCE) -> bool:
    return abs(left - right) <= tolerance


def check_required_files() -> list[str]:
    errors = []

    for file_name in REQUIRED_PROCESSED_FILES:
        path = PROCESSED_DIR / file_name

        if not path.exists():
            errors.append(f"Missing processed file: {path}")

    for file_name in REQUIRED_POWERBI_FILES:
        path = POWERBI_DATASET_DIR / file_name

        if not path.exists():
            errors.append(f"Missing Power BI dataset file: {path}")

    return errors


def validate_opening(opening: pd.DataFrame) -> list[str]:
    errors = []

    qty_in = to_number(opening["qty_in"]).sum()
    qty_out = to_number(opening["qty_out"]).sum()
    net_qty = to_number(opening["net_qty"]).sum()

    calculated_net = qty_in - qty_out

    if not almost_equal(calculated_net, net_qty):
        errors.append(
            f"Opening stock mismatch: qty_in - qty_out = {calculated_net:,.2f}, "
            f"but net_qty = {net_qty:,.2f}"
        )

    if qty_in <= 0:
        errors.append("Opening stock qty_in is zero or negative.")

    return errors


def validate_sales(sales: pd.DataFrame) -> list[str]:
    errors = []

    qty_in = to_number(sales["qty_in"]).sum()
    qty_out = to_number(sales["qty_out"]).sum()
    net_qty = to_number(sales["net_qty"]).sum()

    calculated_net = qty_in - qty_out

    if not almost_equal(calculated_net, net_qty):
        errors.append(
            f"Sales mismatch: qty_in - qty_out = {calculated_net:,.2f}, "
            f"but net_qty = {net_qty:,.2f}"
        )

    if qty_out <= 0:
        errors.append("Sales qty_out is zero or negative.")

    return errors


def validate_receipts(raw_receipts: pd.DataFrame, official_receipts: pd.DataFrame, duplicate_lotrols: pd.DataFrame) -> list[str]:
    errors = []

    raw_qty = to_number(raw_receipts["qty_in"]).sum()
    official_qty = to_number(official_receipts["qty_in"]).sum()

    duplicate_excluded_qty = 0.0

    if not duplicate_lotrols.empty and "duplicate_qty_excluded" in duplicate_lotrols.columns:
        duplicate_excluded_qty = to_number(duplicate_lotrols["duplicate_qty_excluded"]).sum()

    expected_official_qty = raw_qty - duplicate_excluded_qty

    if not almost_equal(expected_official_qty, official_qty):
        errors.append(
            f"Receipt dedup mismatch: raw_qty - duplicate_excluded_qty = {expected_official_qty:,.2f}, "
            f"but official receipt qty = {official_qty:,.2f}"
        )

    duplicated_lotrol_count = official_receipts["lotrol"].duplicated().sum()

    if duplicated_lotrol_count > 0:
        errors.append(
            f"Official receipt movements still contain duplicated LOTROL rows: {duplicated_lotrol_count}"
        )

    return errors


def validate_ledger(ledger: pd.DataFrame) -> list[str]:
    errors = []

    qty_in = to_number(ledger["qty_in"])
    qty_out = to_number(ledger["qty_out"])
    net_qty = to_number(ledger["net_qty"])

    diff = (qty_in - qty_out - net_qty).abs()

    bad_rows = int((diff > TOLERANCE).sum())

    if bad_rows > 0:
        errors.append(f"Ledger has {bad_rows:,} rows where net_qty != qty_in - qty_out.")

    missing_dates = int(ledger["movement_date"].fillna("").astype(str).str.strip().eq("").sum())

    if missing_dates > 0:
        errors.append(f"Ledger has {missing_dates:,} rows with missing movement_date.")

    missing_product_key = int(ledger["product_key"].fillna("").astype(str).str.strip().eq("").sum())

    if missing_product_key > 0:
        errors.append(f"Ledger has {missing_product_key:,} rows with missing product_key.")

    return errors


def validate_monthly_balance(ledger: pd.DataFrame, monthly: pd.DataFrame, company_summary: pd.DataFrame) -> list[str]:
    errors = []

    ledger_net = to_number(ledger["net_qty"]).sum()

    latest_month = monthly["movement_month"].max()

    latest_monthly = monthly[monthly["movement_month"] == latest_month].copy()
    latest_closing = to_number(latest_monthly["closing_balance"]).sum()

    if not almost_equal(ledger_net, latest_closing):
        errors.append(
            f"Monthly balance mismatch: latest closing stock for {latest_month} = {latest_closing:,.2f}, "
            f"but ledger net stock = {ledger_net:,.2f}"
        )

    summary_latest = company_summary[company_summary["movement_month"] == latest_month].copy()

    if summary_latest.empty:
        errors.append(f"Company monthly summary does not contain latest month: {latest_month}")
    else:
        summary_closing = to_number(summary_latest["closing_balance"]).sum()

        if not almost_equal(summary_closing, latest_closing):
            errors.append(
                f"Company summary mismatch: closing_balance = {summary_closing:,.2f}, "
                f"but monthly product closing = {latest_closing:,.2f}"
            )

    return errors


def print_summary(opening, sales, official_receipts, ledger, monthly, duplicate_lotrols) -> None:
    opening_qty = to_number(opening["net_qty"]).sum()
    receipt_qty = to_number(official_receipts["net_qty"]).sum()
    sales_net = to_number(sales["net_qty"]).sum()
    ledger_net = to_number(ledger["net_qty"]).sum()

    latest_month = monthly["movement_month"].max()
    latest_closing = to_number(
        monthly[monthly["movement_month"] == latest_month]["closing_balance"]
    ).sum()

    duplicate_lotrol_count = (
        duplicate_lotrols["lotrol"].nunique()
        if not duplicate_lotrols.empty and "lotrol" in duplicate_lotrols.columns
        else 0
    )

    print()
    print("Validation summary")
    print("-" * 80)
    print(f"Opening stock:              {opening_qty:,.2f}")
    print(f"Official receipt stock in:  {receipt_qty:,.2f}")
    print(f"Sales net impact:           {sales_net:,.2f}")
    print(f"Ledger net stock:           {ledger_net:,.2f}")
    print(f"Latest month:               {latest_month}")
    print(f"Latest closing stock:       {latest_closing:,.2f}")
    print(f"Duplicate LOTROL values:    {duplicate_lotrol_count:,}")
    print("-" * 80)


def main() -> None:
    print("Validating TXP inventory pipeline outputs...")

    errors = []

    errors.extend(check_required_files())

    opening = read_csv(PROCESSED_DIR / "opening_stock_movements.csv")
    sales = read_csv(PROCESSED_DIR / "sales_stock_movements.csv")
    raw_receipts = read_csv(PROCESSED_DIR / "receipt_stock_movements_raw.csv")
    official_receipts = read_csv(PROCESSED_DIR / "receipt_stock_movements.csv")
    duplicate_lotrols = read_csv(PROCESSED_DIR / "duplicate_lotrols.csv")
    ledger = read_csv(PROCESSED_DIR / "stock_movements.csv")
    monthly = read_csv(PROCESSED_DIR / "monthly_inventory_balance.csv")
    company_summary = read_csv(PROCESSED_DIR / "company_monthly_inventory_summary.csv")

    errors.extend(validate_opening(opening))
    errors.extend(validate_sales(sales))
    errors.extend(validate_receipts(raw_receipts, official_receipts, duplicate_lotrols))
    errors.extend(validate_ledger(ledger))
    errors.extend(validate_monthly_balance(ledger, monthly, company_summary))

    print_summary(
        opening=opening,
        sales=sales,
        official_receipts=official_receipts,
        ledger=ledger,
        monthly=monthly,
        duplicate_lotrols=duplicate_lotrols,
    )

    if errors:
        print()
        print("VALIDATION FAILED")
        print("=" * 80)

        for error in errors:
            print(f"- {error}")

        sys.exit(1)

    print()
    print("VALIDATION PASSED")
    print("All core inventory outputs are internally consistent.")


if __name__ == "__main__":
    main()