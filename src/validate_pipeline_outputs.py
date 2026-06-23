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
    "container_import_summary.csv",
    "container_import_header.csv",
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
    "fact_container_import_summary.csv",
    "fact_inventory_exceptions.csv",
    "dim_product_variant.csv",
    "dim_month.csv",
    "dim_container.csv",
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


def real_ibum_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty or "ibum_id" not in df.columns:
        return pd.Series(False, index=df.index)

    ibum = df["ibum_id"].fillna("").astype(str).str.strip()

    return ibum.ne("") & ~ibum.str.upper().str.startswith("MISSING_IBUM::")


def looks_like_source_file(value) -> bool:
    text = str(value or "").strip().lower()

    return text.endswith((".xlsx", ".xls", ".csv"))


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


def validate_container_outputs(
    official_receipts: pd.DataFrame,
    container_summary: pd.DataFrame,
    container_header: pd.DataFrame,
    receipts_quality: pd.DataFrame,
) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    if container_summary.empty:
        errors.append("container_import_summary.csv exists but has no rows.")

    if container_header.empty:
        errors.append("container_import_header.csv exists but has no rows.")

    official_qty = to_number(official_receipts["qty_in"]).sum()

    if "receipt_qty" not in container_summary.columns:
        errors.append("container_import_summary.csv is missing receipt_qty.")
    else:
        container_qty = to_number(container_summary["receipt_qty"]).sum()

        if not almost_equal(official_qty, container_qty):
            errors.append(
                f"Container summary mismatch: receipt_qty = {container_qty:,.2f}, "
                f"but official receipt qty = {official_qty:,.2f}"
            )

    for required_col in ["ibum_id", "container_key"]:
        if required_col not in official_receipts.columns:
            errors.append(f"Official receipt movements are missing {required_col}.")
        if required_col not in container_summary.columns:
            errors.append(f"container_import_summary.csv is missing {required_col}.")
        if required_col not in container_header.columns:
            errors.append(f"container_import_header.csv is missing {required_col}.")

    if {"ibum_id", "container_key", "source_file"}.issubset(official_receipts.columns):
        imports = official_receipts.copy()
        missing_ibum = imports["ibum_id"].fillna("").astype(str).str.strip().eq("")
        expected_fallback = "MISSING_IBUM::" + imports["source_file"].fillna("").astype(str).str.strip()
        bad_container_key = missing_ibum & (
            imports["container_key"].fillna("").astype(str).str.strip() != expected_fallback
        )
        missing_both = missing_ibum & imports["container_key"].fillna("").astype(str).str.strip().eq("")

        if int((bad_container_key | missing_both).sum()) > 0:
            errors.append(
                "Every receipt movement with missing ibum_id must have container_key = MISSING_IBUM::<source_file>."
            )

        missing_ibum_files = set(imports.loc[missing_ibum, "source_file"].dropna().astype(str))

        if missing_ibum_files:
            quality_missing_files = set()

            if not receipts_quality.empty and {"issue_type", "source_file"}.issubset(receipts_quality.columns):
                quality_missing_files = set(
                    receipts_quality.loc[
                        receipts_quality["issue_type"].fillna("").astype(str).eq("MISSING_IBUM_ID"),
                        "source_file",
                    ].dropna().astype(str)
                )

            unflagged = sorted(missing_ibum_files - quality_missing_files)

            if unflagged:
                errors.append(
                    "Receipt files with missing IBUM were not flagged in receipts_quality_checks.csv: "
                    + ", ".join(unflagged)
                )
            else:
                warnings.append(
                    f"{len(missing_ibum_files):,} receipt files are missing IBUM. This is allowed but flagged as MISSING_IBUM_ID."
                )

    return errors, warnings


def validate_ledger(ledger: pd.DataFrame) -> list[str]:
    errors = []

    required_traceability_cols = [
        "load_id",
        "ibum_id",
        "container_key",
        "movement_group",
        "movement_subtype",
        "traceability_level",
    ]

    missing_traceability_cols = [col for col in required_traceability_cols if col not in ledger.columns]

    if missing_traceability_cols:
        errors.append(f"Ledger is missing traceability columns: {missing_traceability_cols}")
        return errors

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

    imports = ledger[ledger["movement_group"].fillna("").astype(str).str.upper().eq("IMPORT")].copy()

    if not imports.empty:
        ibum = imports["ibum_id"].fillna("").astype(str).str.strip()
        container_key = imports["container_key"].fillna("").astype(str).str.strip()
        source_file = imports["source_file"].fillna("").astype(str).str.strip()
        expected_fallback = "MISSING_IBUM::" + source_file

        bad_imports = (ibum.eq("") & container_key.ne(expected_fallback)) | container_key.eq("")

        if int(bad_imports.sum()) > 0:
            errors.append(
                f"Ledger has {int(bad_imports.sum()):,} import rows without ibum_id or valid missing-IBUM container_key."
            )

    return errors


def validate_powerbi_exports() -> list[str]:
    errors = []

    stock_path = POWERBI_DATASET_DIR / "fact_stock_movements.csv"
    container_path = POWERBI_DATASET_DIR / "fact_container_import_summary.csv"
    dim_container_path = POWERBI_DATASET_DIR / "dim_container.csv"

    stock = read_csv(stock_path)
    container_summary = read_csv(container_path)
    dim_container = read_csv(dim_container_path)

    required_stock_cols = [
        "ibum_id",
        "container_key",
        "movement_group",
        "movement_subtype",
        "traceability_level",
    ]

    missing_stock_cols = [col for col in required_stock_cols if col not in stock.columns]

    if missing_stock_cols:
        errors.append(f"Power BI fact_stock_movements.csv is missing columns: {missing_stock_cols}")

    for table_name, df in [
        ("fact_container_import_summary.csv", container_summary),
        ("dim_container.csv", dim_container),
    ]:
        if "container_key" not in df.columns:
            errors.append(f"Power BI {table_name} is missing container_key.")
        if "ibum_id" not in df.columns:
            errors.append(f"Power BI {table_name} is missing ibum_id.")

    required_container_cols = [
        "source_files",
        "total_receipt_qty",
        "source_file_count",
    ]
    missing_dim_cols = [col for col in required_container_cols if col not in dim_container.columns]

    if missing_dim_cols:
        errors.append(f"Power BI dim_container.csv is missing columns: {missing_dim_cols}")

    required_summary_cols = [
        "source_files",
        "receipt_qty",
        "reference",
        "color_normalized",
        "product_key",
    ]
    missing_summary_cols = [col for col in required_summary_cols if col not in container_summary.columns]

    if missing_summary_cols:
        errors.append(
            f"Power BI fact_container_import_summary.csv is missing columns: {missing_summary_cols}"
        )

    if {"ibum_id", "container_key"}.issubset(dim_container.columns):
        real_dim = dim_container[real_ibum_mask(dim_container)].copy()

        duplicate_ibums = real_dim["ibum_id"].fillna("").astype(str).str.strip().duplicated().sum()

        if duplicate_ibums > 0:
            errors.append(
                f"Power BI dim_container.csv has {duplicate_ibums:,} duplicate real IBUM business rows."
            )

        fake_ibums = real_dim[
            real_dim["ibum_id"].apply(looks_like_source_file)
            | real_dim["container_key"].fillna("").astype(str).str.upper().str.startswith("MISSING_IBUM::")
        ]

        if not fake_ibums.empty:
            errors.append("Power BI dim_container.csv contains file names or missing-IBUM keys as business IBUM rows.")

        if {"movement_group", "qty_in", "ibum_id"}.issubset(stock.columns) and "total_receipt_qty" in real_dim.columns:
            imports = stock[
                stock["movement_group"].fillna("").astype(str).str.upper().eq("IMPORT")
                & real_ibum_mask(stock)
            ].copy()

            if not imports.empty:
                imports["qty_in"] = to_number(imports["qty_in"])
                movement_totals = (
                    imports.groupby("ibum_id", as_index=False)
                    .agg(import_qty=("qty_in", "sum"))
                )
                dim_totals = real_dim[["ibum_id", "total_receipt_qty"]].copy()
                dim_totals["total_receipt_qty"] = to_number(dim_totals["total_receipt_qty"])
                comparison = dim_totals.merge(movement_totals, on="ibum_id", how="outer").fillna(0)
                diff = (comparison["total_receipt_qty"] - comparison["import_qty"]).abs()
                bad_totals = comparison[diff > TOLERANCE]

                if not bad_totals.empty:
                    errors.append(
                        "Power BI dim_container.csv total_receipt_qty does not match "
                        "fact_stock_movements import qty by real IBUM."
                    )

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
    if "ibum_id" in official_receipts.columns:
        missing_ibum_files = official_receipts[
            official_receipts["ibum_id"].fillna("").astype(str).str.strip().eq("")
        ]["source_file"].nunique()
        print(f"Receipt files missing IBUM:  {missing_ibum_files:,}")
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
    container_summary = read_csv(PROCESSED_DIR / "container_import_summary.csv")
    container_header = read_csv(PROCESSED_DIR / "container_import_header.csv")
    receipts_quality = read_csv(PROCESSED_DIR / "receipts_quality_checks.csv")
    ledger = read_csv(PROCESSED_DIR / "stock_movements.csv")
    monthly = read_csv(PROCESSED_DIR / "monthly_inventory_balance.csv")
    company_summary = read_csv(PROCESSED_DIR / "company_monthly_inventory_summary.csv")

    errors.extend(validate_opening(opening))
    errors.extend(validate_sales(sales))
    errors.extend(validate_receipts(raw_receipts, official_receipts, duplicate_lotrols))
    container_errors, warnings = validate_container_outputs(
        official_receipts=official_receipts,
        container_summary=container_summary,
        container_header=container_header,
        receipts_quality=receipts_quality,
    )
    errors.extend(container_errors)
    errors.extend(validate_ledger(ledger))
    errors.extend(validate_monthly_balance(ledger, monthly, company_summary))
    errors.extend(validate_powerbi_exports())

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

    if warnings:
        print()
        print("VALIDATION WARNINGS")
        print("=" * 80)

        for warning in warnings:
            print(f"- {warning}")

    print()
    print("VALIDATION PASSED")
    print("All core inventory outputs are internally consistent.")


if __name__ == "__main__":
    main()
