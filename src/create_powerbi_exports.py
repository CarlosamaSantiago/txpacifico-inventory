from pathlib import Path
import calendar
import re

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
POWERBI_DATASET_DIR = PROJECT_ROOT / "reports" / "powerbi" / "dataset"


INPUTS = {
    "stock_movements": PROCESSED_DIR / "stock_movements.csv",
    "monthly_inventory_balance": PROCESSED_DIR / "monthly_inventory_balance.csv",
    "current_inventory_balance": PROCESSED_DIR / "current_inventory_balance.csv",
    "company_monthly_inventory_summary": PROCESSED_DIR / "company_monthly_inventory_summary.csv",
    "duplicate_lotrols": PROCESSED_DIR / "duplicate_lotrols.csv",
    "product_master_candidate": PROCESSED_DIR / "product_master_candidate.csv",
}


QUALITY_FILES = [
    PROCESSED_DIR / "opening_stock_quality_checks.csv",
    PROCESSED_DIR / "sales_quality_checks.csv",
    PROCESSED_DIR / "receipts_quality_checks.csv",
    PROCESSED_DIR / "stock_movements_quality_checks.csv",
    PROCESSED_DIR / "negative_inventory_alerts.csv",
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"WARNING: Missing file: {path}")
        return pd.DataFrame()

    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


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


def clean_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def prepare_stock_movements(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_text_columns(df)

    numeric_cols = [
        "qty_in",
        "qty_out",
        "net_qty",
        "roll_count",
        "subtotal",
        "weight",
        "entrada",
        "salida",
        "asignacion",
        "saldo",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    cols = [
        "movement_id",
        "movement_date",
        "movement_month",
        "movement_source",
        "movement_type",
        "document",
        "reference",
        "description",
        "color_original",
        "color_normalized",
        "product_key",
        "lot",
        "roll",
        "lotrol",
        "location",
        "qty_in",
        "qty_out",
        "net_qty",
        "unit_of_measure",
        "source_file",
        "source_sheet",
        "source_row",
        "validation_status",
    ]

    existing_cols = [col for col in cols if col in df.columns]

    return df[existing_cols].copy()


def prepare_monthly_balance(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_text_columns(df)

    numeric_cols = [
        "opening_balance",
        "opening_stock_qty",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
        "other_qty_in",
        "other_qty_out",
        "net_change",
        "closing_balance",
        "calculated_closing_balance",
        "movement_rows",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    bool_cols = [
        "has_negative_closing_balance",
        "has_month_movement",
    ]

    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.upper().isin(["TRUE", "1", "YES"])

    return df.copy()


def build_dim_product_variant(product_master: pd.DataFrame, stock_movements: pd.DataFrame) -> pd.DataFrame:
    if product_master.empty:
        source = stock_movements.copy()

        product_master = (
            source.groupby(["product_key"], as_index=False)
            .agg(
                reference=("reference", "first"),
                color_normalized=("color_normalized", "first"),
                descriptions=("description", lambda values: " | ".join(sorted(set(v for v in values if v)))),
                first_movement_date=("movement_date", "min"),
                last_movement_date=("movement_date", "max"),
                total_qty_in=("qty_in", "sum"),
                total_qty_out=("qty_out", "sum"),
                current_net_qty=("net_qty", "sum"),
                movement_rows=("movement_id", "count"),
                sources=("movement_source", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            )
        )

    product_master = clean_text_columns(product_master)

    numeric_cols = [
        "total_qty_in",
        "total_qty_out",
        "current_net_qty",
        "movement_rows",
    ]

    for col in numeric_cols:
        if col in product_master.columns:
            product_master[col] = to_number(product_master[col])

    product_master["reference_prefix_2"] = product_master["reference"].str[:2]
    product_master["reference_prefix_4"] = product_master["reference"].str[:4]

    product_master["product_family"] = product_master["reference_prefix_2"].map(
        {
            "01": "PERUANA / RIB / CUELLOS",
            "02": "FLEECE / F SERIES",
            "03": "PRODUCT FAMILY 03",
            "04": "PRODUCT FAMILY 04",
            "05": "BURDA / RIB BURDA",
            "06": "PRODUCT FAMILY 06",
            "07": "QATAR / PREMIUM",
        }
    ).fillna("UNMAPPED FAMILY")

    preferred_cols = [
        "product_key",
        "reference",
        "reference_prefix_2",
        "reference_prefix_4",
        "product_family",
        "color_normalized",
        "descriptions",
        "first_movement_date",
        "last_movement_date",
        "total_qty_in",
        "total_qty_out",
        "current_net_qty",
        "movement_rows",
        "sources",
    ]

    existing_cols = [col for col in preferred_cols if col in product_master.columns]

    return product_master[existing_cols].sort_values(["reference", "color_normalized"])


def build_dim_month(monthly_balance: pd.DataFrame) -> pd.DataFrame:
    min_month = monthly_balance["movement_month"].min()
    max_month = monthly_balance["movement_month"].max()

    months = pd.period_range(min_month, max_month, freq="M")

    rows = []

    for period in months:
        month_number = period.month

        rows.append(
            {
                "movement_month": str(period),
                "month_start_date": period.to_timestamp().strftime("%Y-%m-%d"),
                "year": period.year,
                "month_number": month_number,
                "month_name": calendar.month_name[month_number],
                "month_short_name": calendar.month_abbr[month_number],
                "quarter": f"Q{period.quarter}",
                "year_month_label": f"{period.year}-{month_number:02d}",
                "sort_key": period.year * 100 + month_number,
            }
        )

    return pd.DataFrame(rows)


def build_exceptions_table() -> pd.DataFrame:
    frames = []

    for path in QUALITY_FILES:
        if not path.exists():
            continue

        df = read_csv(path)

        if df.empty:
            continue

        df["exception_source_file"] = path.name

        if "issue_type" not in df.columns:
            if path.name == "negative_inventory_alerts.csv":
                df["issue_type"] = "NEGATIVE_INVENTORY"
            else:
                df["issue_type"] = "UNCLASSIFIED_EXCEPTION"

        if "issue_detail" not in df.columns:
            df["issue_detail"] = ""

        frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "issue_type",
                "issue_detail",
                "exception_source_file",
            ]
        )

    exceptions = pd.concat(frames, ignore_index=True, sort=False)
    exceptions = clean_text_columns(exceptions)

    return exceptions


def write_readme() -> None:
    readme_path = POWERBI_DATASET_DIR / "README_POWERBI_DATASET.md"

    content = """# TXP Power BI Dataset

Use these CSV files as the Power BI semantic model.

## Recommended relationships

- dim_product_variant[product_key] 1 -> many fact_stock_movements[product_key]
- dim_product_variant[product_key] 1 -> many fact_monthly_inventory_balance[product_key]
- dim_month[movement_month] 1 -> many fact_stock_movements[movement_month]
- dim_month[movement_month] 1 -> many fact_monthly_inventory_balance[movement_month]
- dim_month[movement_month] 1 -> many fact_company_monthly_summary[movement_month]

## Main fact tables

- fact_stock_movements: detailed inventory ledger.
- fact_monthly_inventory_balance: monthly stock balance by product/color.
- fact_company_monthly_summary: company-level monthly stock balance.
- fact_duplicate_lotrols: duplicated receipt roll alerts.
- fact_inventory_exceptions: combined data quality alerts.

## Core measures to create in Power BI

Current Stock = SUM(fact_monthly_inventory_balance[closing_balance])

Total Imports = SUM(fact_monthly_inventory_balance[imports_qty])

Total Sales = SUM(fact_monthly_inventory_balance[sales_qty])

Total Returns / Adjustments = SUM(fact_monthly_inventory_balance[returns_adjustments_qty])

Net Change = SUM(fact_monthly_inventory_balance[net_change])

Negative Stock Items = COUNTROWS(FILTER(fact_monthly_inventory_balance, fact_monthly_inventory_balance[has_negative_closing_balance] = TRUE()))
"""

    readme_path.write_text(content, encoding="utf-8")


def main() -> None:
    POWERBI_DATASET_DIR.mkdir(parents=True, exist_ok=True)

    print("Creating Power BI export dataset...")

    stock_movements = prepare_stock_movements(read_csv(INPUTS["stock_movements"]))
    monthly_balance = prepare_monthly_balance(read_csv(INPUTS["monthly_inventory_balance"]))
    company_summary = prepare_monthly_balance(read_csv(INPUTS["company_monthly_inventory_summary"]))
    duplicate_lotrols = clean_text_columns(read_csv(INPUTS["duplicate_lotrols"]))
    product_master = read_csv(INPUTS["product_master_candidate"])

    dim_product_variant = build_dim_product_variant(product_master, stock_movements)
    dim_month = build_dim_month(monthly_balance)
    exceptions = build_exceptions_table()

    outputs = {
        "fact_stock_movements.csv": stock_movements,
        "fact_monthly_inventory_balance.csv": monthly_balance,
        "fact_company_monthly_summary.csv": company_summary,
        "fact_duplicate_lotrols.csv": duplicate_lotrols,
        "fact_inventory_exceptions.csv": exceptions,
        "dim_product_variant.csv": dim_product_variant,
        "dim_month.csv": dim_month,
    }

    for file_name, df in outputs.items():
        output_path = POWERBI_DATASET_DIR / file_name
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"Wrote {file_name}: {len(df):,} rows")

    write_readme()

    print("Done.")
    print(f"Power BI dataset folder: {POWERBI_DATASET_DIR}")


if __name__ == "__main__":
    main()