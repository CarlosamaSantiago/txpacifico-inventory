from pathlib import Path
import re

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

LEDGER_PATH = PROCESSED_DIR / "stock_movements.csv"


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

    cleaned = series.apply(clean_value)

    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def classify_movements(ledger: pd.DataFrame) -> pd.DataFrame:
    ledger = ledger.copy()

    ledger["opening_stock_qty"] = 0.0
    ledger["imports_qty"] = 0.0
    ledger["sales_qty"] = 0.0
    ledger["returns_adjustments_qty"] = 0.0
    ledger["other_qty_in"] = 0.0
    ledger["other_qty_out"] = 0.0

    opening_mask = ledger["movement_type"].str.startswith("OPENING", na=False)
    receipt_mask = ledger["movement_type"].eq("CONTAINER_RECEIPT")
    sale_mask = ledger["movement_type"].eq("SALE")
    return_mask = ledger["movement_type"].eq("SALES_RETURN_OR_ADJUSTMENT")

    ledger.loc[opening_mask, "opening_stock_qty"] = ledger.loc[opening_mask, "qty_in"]
    ledger.loc[receipt_mask, "imports_qty"] = ledger.loc[receipt_mask, "qty_in"]
    ledger.loc[sale_mask, "sales_qty"] = ledger.loc[sale_mask, "qty_out"]
    ledger.loc[return_mask, "returns_adjustments_qty"] = ledger.loc[return_mask, "qty_in"]

    known_mask = opening_mask | receipt_mask | sale_mask | return_mask

    ledger.loc[~known_mask, "other_qty_in"] = ledger.loc[~known_mask, "qty_in"]
    ledger.loc[~known_mask, "other_qty_out"] = ledger.loc[~known_mask, "qty_out"]

    return ledger


def build_product_master(ledger: pd.DataFrame) -> pd.DataFrame:
    product_master = (
        ledger.groupby(["product_key"], as_index=False)
        .agg(
            reference=("reference", "first"),
            color_normalized=("color_normalized", "first"),
            description=("description", lambda values: next((v for v in values if v), "")),
            first_movement_month=("movement_month", "min"),
            last_movement_month=("movement_month", "max"),
        )
    )

    return product_master


def build_month_grid(ledger: pd.DataFrame, product_master: pd.DataFrame) -> pd.DataFrame:
    min_month = ledger["movement_month"].min()
    max_month = ledger["movement_month"].max()

    months = pd.period_range(min_month, max_month, freq="M").astype(str)

    month_grid = pd.MultiIndex.from_product(
        [months, product_master["product_key"]],
        names=["movement_month", "product_key"],
    ).to_frame(index=False)

    month_grid = month_grid.merge(product_master, on="product_key", how="left")

    return month_grid


def build_monthly_balance(ledger: pd.DataFrame) -> pd.DataFrame:
    product_master = build_product_master(ledger)
    month_grid = build_month_grid(ledger, product_master)

    monthly_movements = (
        ledger.groupby(["movement_month", "product_key"], as_index=False)
        .agg(
            opening_stock_qty=("opening_stock_qty", "sum"),
            imports_qty=("imports_qty", "sum"),
            sales_qty=("sales_qty", "sum"),
            returns_adjustments_qty=("returns_adjustments_qty", "sum"),
            other_qty_in=("other_qty_in", "sum"),
            other_qty_out=("other_qty_out", "sum"),
            qty_in=("qty_in", "sum"),
            qty_out=("qty_out", "sum"),
            net_qty=("net_qty", "sum"),
            movement_rows=("movement_id", "count"),
        )
    )

    balance = month_grid.merge(
        monthly_movements,
        on=["movement_month", "product_key"],
        how="left",
    )

    numeric_cols = [
        "opening_stock_qty",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
        "other_qty_in",
        "other_qty_out",
        "qty_in",
        "qty_out",
        "net_qty",
        "movement_rows",
    ]

    for col in numeric_cols:
        balance[col] = balance[col].fillna(0.0)

    balance = balance.sort_values(
        ["product_key", "movement_month"]
    ).reset_index(drop=True)

    balance["net_change"] = (
        balance["opening_stock_qty"]
        + balance["imports_qty"]
        + balance["returns_adjustments_qty"]
        + balance["other_qty_in"]
        - balance["sales_qty"]
        - balance["other_qty_out"]
    )

    balance["closing_balance"] = balance.groupby("product_key")["net_change"].cumsum()

    balance["opening_balance"] = (
        balance.groupby("product_key")["closing_balance"].shift(1).fillna(0.0)
    )

    balance["calculated_closing_balance"] = (
        balance["opening_balance"] + balance["net_change"]
    )

    balance["has_negative_closing_balance"] = balance["closing_balance"] < -0.0001

    balance["has_month_movement"] = balance["movement_rows"] > 0

    ordered_cols = [
        "movement_month",
        "reference",
        "description",
        "color_normalized",
        "product_key",
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
        "has_negative_closing_balance",
        "has_month_movement",
        "movement_rows",
        "first_movement_month",
        "last_movement_month",
    ]

    return balance[ordered_cols].copy()


def build_current_inventory(monthly_balance: pd.DataFrame) -> pd.DataFrame:
    latest_month = monthly_balance["movement_month"].max()

    current = monthly_balance[
        monthly_balance["movement_month"] == latest_month
    ].copy()

    current = current.sort_values(
        ["reference", "color_normalized"]
    ).reset_index(drop=True)

    return current


def build_negative_inventory_alerts(monthly_balance: pd.DataFrame) -> pd.DataFrame:
    negative = monthly_balance[
        monthly_balance["has_negative_closing_balance"]
    ].copy()

    return negative.sort_values(
        ["movement_month", "reference", "color_normalized"]
    ).reset_index(drop=True)


def build_company_monthly_summary(monthly_balance: pd.DataFrame) -> pd.DataFrame:
    summary = (
        monthly_balance.groupby("movement_month", as_index=False)
        .agg(
            opening_balance=("opening_balance", "sum"),
            opening_stock_qty=("opening_stock_qty", "sum"),
            imports_qty=("imports_qty", "sum"),
            sales_qty=("sales_qty", "sum"),
            returns_adjustments_qty=("returns_adjustments_qty", "sum"),
            other_qty_in=("other_qty_in", "sum"),
            other_qty_out=("other_qty_out", "sum"),
            net_change=("net_change", "sum"),
            closing_balance=("closing_balance", "sum"),
            product_keys_with_movement=("has_month_movement", "sum"),
            negative_product_keys=("has_negative_closing_balance", "sum"),
        )
    )

    return summary


def main() -> None:
    if not LEDGER_PATH.exists():
        raise FileNotFoundError(
            f"Missing stock movements ledger: {LEDGER_PATH}. Run src/build_ledger.py first."
        )

    print(f"Reading ledger: {LEDGER_PATH}")

    ledger = pd.read_csv(LEDGER_PATH, dtype=str)

    required_columns = [
        "movement_id",
        "movement_date",
        "movement_month",
        "movement_type",
        "reference",
        "description",
        "color_normalized",
        "product_key",
        "qty_in",
        "qty_out",
        "net_qty",
    ]

    missing = [col for col in required_columns if col not in ledger.columns]

    if missing:
        raise ValueError(f"Ledger is missing required columns: {missing}")

    for col in ["qty_in", "qty_out", "net_qty"]:
        ledger[col] = to_number(ledger[col])

    text_cols = [
        "movement_id",
        "movement_month",
        "movement_type",
        "reference",
        "description",
        "color_normalized",
        "product_key",
    ]

    for col in text_cols:
        ledger[col] = ledger[col].fillna("").astype(str).str.strip()

    ledger = ledger[
        (ledger["movement_month"] != "")
        & (ledger["product_key"] != "")
    ].copy()

    ledger = classify_movements(ledger)

    monthly_balance = build_monthly_balance(ledger)
    current_inventory = build_current_inventory(monthly_balance)
    negative_alerts = build_negative_inventory_alerts(monthly_balance)
    company_summary = build_company_monthly_summary(monthly_balance)

    monthly_path = PROCESSED_DIR / "monthly_inventory_balance.csv"
    current_path = PROCESSED_DIR / "current_inventory_balance.csv"
    negative_path = PROCESSED_DIR / "negative_inventory_alerts.csv"
    company_summary_path = PROCESSED_DIR / "company_monthly_inventory_summary.csv"

    monthly_balance.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    current_inventory.to_csv(current_path, index=False, encoding="utf-8-sig")
    negative_alerts.to_csv(negative_path, index=False, encoding="utf-8-sig")
    company_summary.to_csv(company_summary_path, index=False, encoding="utf-8-sig")

    latest_month = monthly_balance["movement_month"].max()
    latest_stock = current_inventory["closing_balance"].sum()

    print("Done.")
    print(f"Months included: {monthly_balance['movement_month'].min()} to {latest_month}")
    print(f"Product keys: {monthly_balance['product_key'].nunique():,}")
    print(f"Monthly balance rows: {len(monthly_balance):,}")
    print(f"Latest inventory month: {latest_month}")
    print(f"Latest closing stock: {latest_stock:,.2f}")
    print(f"Negative inventory alert rows: {len(negative_alerts):,}")
    print(f"Wrote: {monthly_path}")
    print(f"Wrote: {current_path}")
    print(f"Wrote: {negative_path}")
    print(f"Wrote: {company_summary_path}")


if __name__ == "__main__":
    main()