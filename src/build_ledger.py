from pathlib import Path

import pandas as pd
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


INPUT_FILES = {
    "opening": PROCESSED_DIR / "opening_stock_movements.csv",
    "sales": PROCESSED_DIR / "sales_stock_movements.csv",
    "receipts": PROCESSED_DIR / "receipt_stock_movements.csv",
}


STANDARD_COLUMNS = [
    "movement_id",
    "movement_date",
    "movement_month",
    "movement_type",
    "load_id",
    "ibum_id",
    "container_key",
    "movement_group",
    "movement_subtype",
    "traceability_level",
    "document",
    "reference",
    "description",
    "color_code",
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
    "period_start",
    "period_end",
    "roll_count",
    "subtotal",
    "weight",
    "entrada",
    "salida",
    "asignacion",
    "saldo",
]


def read_movements(path: Path, source_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {source_name} movements file: {path}")

    df = pd.read_csv(path, dtype=str)

    df["movement_source"] = source_name

    return df


def ensure_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in STANDARD_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    extra_columns = [column for column in df.columns if column not in STANDARD_COLUMNS + ["movement_source"]]

    ordered_columns = STANDARD_COLUMNS + ["movement_source"] + extra_columns

    return df[ordered_columns].copy()


def to_number(series: pd.Series) -> pd.Series:
    def clean_value(value):
        if pd.isna(value):
            return ""

        text = str(value).strip()
        text = text.replace("\ufeff", "")
        text = text.replace("\xa0", "")
        text = text.replace(" ", "")

        # Handle negative accounting format: (123.45)
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]

        # Handle both formats:
        # 1,234.56 -> 1234.56
        # 1.234,56 -> 1234.56
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


def default_movement_group(movement_type: str, movement_source: str) -> str:
    movement_type = str(movement_type).strip().upper()
    movement_source = str(movement_source).strip().lower()

    if movement_type.startswith("OPENING") or movement_source == "opening":
        return "OPENING"
    if movement_type == "CONTAINER_RECEIPT" or movement_source == "receipts":
        return "IMPORT"
    if movement_type in {"SALE", "SALES_RETURN_OR_ADJUSTMENT"} or movement_source == "sales":
        return "SALE"

    return "OTHER"


def default_movement_subtype(movement_type: str) -> str:
    movement_type = str(movement_type).strip().upper()

    if movement_type == "OPENING_PHYSICAL_ROLL":
        return "PHYSICAL_ROLL"
    if movement_type == "OPENING_RIB_COLLAR_AGG":
        return "RIB_COLLAR_AGG"
    if movement_type == "CONTAINER_RECEIPT":
        return "CONTAINER_RECEIPT"
    if movement_type == "SALE":
        return "SALE"
    if movement_type == "SALES_RETURN_OR_ADJUSTMENT":
        return "RETURN_OR_ADJUSTMENT"

    return movement_type or "OTHER"


def default_traceability_level(movement_type: str, movement_source: str) -> str:
    movement_type = str(movement_type).strip().upper()
    movement_source = str(movement_source).strip().lower()

    if movement_type == "OPENING_PHYSICAL_ROLL":
        return "ROLL"
    if movement_type == "OPENING_RIB_COLLAR_AGG":
        return "AGGREGATE"
    if movement_type == "CONTAINER_RECEIPT" or movement_source == "receipts":
        return "ROLL"
    if movement_type in {"SALE", "SALES_RETURN_OR_ADJUSTMENT"} or movement_source == "sales":
        return "MONTHLY_REPORT_ROW"

    return "UNKNOWN"


def parse_movement_dates(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()

    parsed = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")

    missing_mask = parsed.isna()

    if missing_mask.any():
        parsed_dayfirst = pd.to_datetime(
            values[missing_mask],
            dayfirst=True,
            errors="coerce",
        )

        parsed.loc[missing_mask] = parsed_dayfirst

    return parsed

def clean_ledger(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    numeric_columns = [
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

    for column in numeric_columns:
        if column in df.columns:
            df[column] = to_number(df[column])

    text_columns = [
        "movement_date",
        "movement_month",
        "movement_type",
        "load_id",
        "ibum_id",
        "container_key",
        "movement_group",
        "movement_subtype",
        "traceability_level",
        "document",
        "reference",
        "description",
        "color_code",
        "color_original",
        "color_normalized",
        "product_key",
        "lot",
        "roll",
        "lotrol",
        "location",
        "unit_of_measure",
        "source_file",
        "source_sheet",
        "validation_status",
        "period_start",
        "period_end",
        "movement_source",
    ]

    for column in text_columns:
        if column in df.columns:
            df[column] = df[column].fillna("").astype(str).str.strip()

    df["load_id"] = df["load_id"].replace("", "LOCAL_RUN")

    missing_container_key = (
        (df["movement_source"] == "receipts")
        & (df["container_key"] == "")
    )
    df.loc[missing_container_key & (df["ibum_id"] != ""), "container_key"] = df.loc[
        missing_container_key & (df["ibum_id"] != ""),
        "ibum_id",
    ]
    df.loc[missing_container_key & (df["ibum_id"] == ""), "container_key"] = (
        "MISSING_IBUM::" + df.loc[missing_container_key & (df["ibum_id"] == ""), "source_file"]
    )

    df.loc[df["movement_group"] == "", "movement_group"] = df.loc[
        df["movement_group"] == ""
    ].apply(
        lambda row: default_movement_group(row["movement_type"], row["movement_source"]),
        axis=1,
    )
    df.loc[df["movement_subtype"] == "", "movement_subtype"] = df.loc[
        df["movement_subtype"] == ""
    ]["movement_type"].apply(default_movement_subtype)
    df.loc[df["traceability_level"] == "", "traceability_level"] = df.loc[
        df["traceability_level"] == ""
    ].apply(
        lambda row: default_traceability_level(row["movement_type"], row["movement_source"]),
        axis=1,
    )

    df["movement_date"] = parse_movement_dates(df["movement_date"])
    df["movement_month"] = df["movement_date"].dt.strftime("%Y-%m")

    # Recalculate net quantity to avoid trusting source files blindly.
    df["calculated_net_qty"] = df["qty_in"] - df["qty_out"]
    df["net_qty_difference"] = df["net_qty"] - df["calculated_net_qty"]

    df["net_qty"] = df["calculated_net_qty"]

    df["has_net_qty_error"] = df["net_qty_difference"].abs() > 0.0001

    df = df.sort_values(
        [
            "movement_date",
            "movement_type",
            "reference",
            "color_normalized",
            "source_file",
            "source_row",
        ],
        na_position="last",
    ).reset_index(drop=True)

    df["movement_id"] = [
        f"MOV{str(index + 1).zfill(9)}"
        for index in range(len(df))
    ]

    return df


def build_summary_by_type(ledger: pd.DataFrame) -> pd.DataFrame:
    return (
        ledger.groupby(["movement_source", "movement_type"], as_index=False)
        .agg(
            movement_rows=("movement_id", "count"),
            qty_in=("qty_in", "sum"),
            qty_out=("qty_out", "sum"),
            net_qty=("net_qty", "sum"),
            unique_product_keys=("product_key", "nunique"),
            unique_lotrols=("lotrol", lambda values: values[values != ""].nunique()),
        )
        .sort_values(["movement_source", "movement_type"])
    )


def build_summary_by_month(ledger: pd.DataFrame) -> pd.DataFrame:
    return (
        ledger.groupby(["movement_month", "movement_source", "movement_type"], as_index=False)
        .agg(
            movement_rows=("movement_id", "count"),
            qty_in=("qty_in", "sum"),
            qty_out=("qty_out", "sum"),
            net_qty=("net_qty", "sum"),
        )
        .sort_values(["movement_month", "movement_source", "movement_type"])
    )


def build_product_master_candidate(ledger: pd.DataFrame) -> pd.DataFrame:
    product_master = (
        ledger.groupby(["reference", "color_normalized", "product_key"], as_index=False)
        .agg(
            descriptions=("description", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            first_movement_date=("movement_date", "min"),
            last_movement_date=("movement_date", "max"),
            total_qty_in=("qty_in", "sum"),
            total_qty_out=("qty_out", "sum"),
            current_net_qty=("net_qty", "sum"),
            movement_rows=("movement_id", "count"),
            sources=("movement_source", lambda values: " | ".join(sorted(set(values)))),
        )
    )

    product_master["first_movement_date"] = product_master["first_movement_date"].dt.strftime("%Y-%m-%d")
    product_master["last_movement_date"] = product_master["last_movement_date"].dt.strftime("%Y-%m-%d")

    return product_master.sort_values(["reference", "color_normalized"])


def build_ledger_quality_checks(ledger: pd.DataFrame) -> pd.DataFrame:
    quality_rows = []

    net_qty_errors = ledger[ledger["has_net_qty_error"]].copy()

    if not net_qty_errors.empty:
        net_qty_errors["issue_type"] = "NET_QTY_RECALCULATED"
        net_qty_errors["issue_detail"] = "Original net_qty did not match qty_in - qty_out. Ledger recalculated net_qty."
        quality_rows.append(net_qty_errors)

    missing_dates = ledger[ledger["movement_date"].isna()].copy()

    if not missing_dates.empty:
        missing_dates["issue_type"] = "MISSING_MOVEMENT_DATE"
        missing_dates["issue_detail"] = "Movement date is missing or invalid."
        quality_rows.append(missing_dates)

    missing_product_key = ledger[
        (ledger["reference"] == "")
        | (ledger["color_normalized"] == "")
        | (ledger["product_key"] == "")
    ].copy()

    if not missing_product_key.empty:
        missing_product_key["issue_type"] = "MISSING_PRODUCT_KEY"
        missing_product_key["issue_detail"] = "Reference, normalized color, or product key is missing."
        quality_rows.append(missing_product_key)

    if not quality_rows:
        return pd.DataFrame(
            columns=[
                "issue_type",
                "issue_detail",
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
                "source_file",
                "source_sheet",
                "source_row",
                "movement_source",
            ]
        )

    quality = pd.concat(quality_rows, ignore_index=True)

    return quality[
        [
            "issue_type",
            "issue_detail",
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
            "source_file",
            "source_sheet",
            "source_row",
            "movement_source",
        ]
    ].copy()


def main() -> None:
    print("Reading movement files...")

    opening = read_movements(INPUT_FILES["opening"], "opening")
    sales = read_movements(INPUT_FILES["sales"], "sales")
    receipts = read_movements(INPUT_FILES["receipts"], "receipts")

    print(f"Opening rows: {len(opening):,}")
    print(f"Sales rows: {len(sales):,}")
    print(f"Receipt rows: {len(receipts):,}")

    opening = ensure_standard_columns(opening)
    sales = ensure_standard_columns(sales)
    receipts = ensure_standard_columns(receipts)

    ledger = pd.concat([opening, receipts, sales], ignore_index=True)
    ledger = clean_ledger(ledger)

    summary_by_type = build_summary_by_type(ledger)
    summary_by_month = build_summary_by_month(ledger)
    product_master_candidate = build_product_master_candidate(ledger)
    ledger_quality = build_ledger_quality_checks(ledger)

    ledger_path = PROCESSED_DIR / "stock_movements.csv"
    summary_type_path = PROCESSED_DIR / "stock_movements_summary_by_type.csv"
    summary_month_path = PROCESSED_DIR / "stock_movements_summary_by_month.csv"
    product_master_path = PROCESSED_DIR / "product_master_candidate.csv"
    quality_path = PROCESSED_DIR / "stock_movements_quality_checks.csv"

    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    summary_by_type.to_csv(summary_type_path, index=False, encoding="utf-8-sig")
    summary_by_month.to_csv(summary_month_path, index=False, encoding="utf-8-sig")
    product_master_candidate.to_csv(product_master_path, index=False, encoding="utf-8-sig")
    ledger_quality.to_csv(quality_path, index=False, encoding="utf-8-sig")

    print("Done.")
    print(f"Total ledger rows: {len(ledger):,}")
    print(f"Total qty in: {ledger['qty_in'].sum():,.2f}")
    print(f"Total qty out: {ledger['qty_out'].sum():,.2f}")
    print(f"Current net stock from ledger: {ledger['net_qty'].sum():,.2f}")
    print(f"Unique product keys: {ledger['product_key'].nunique():,}")
    print(f"Quality check rows: {len(ledger_quality):,}")
    print(f"Wrote: {ledger_path}")
    print(f"Wrote: {summary_type_path}")
    print(f"Wrote: {summary_month_path}")
    print(f"Wrote: {product_master_path}")
    print(f"Wrote: {quality_path}")


if __name__ == "__main__":
    main()
