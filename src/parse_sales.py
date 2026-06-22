from pathlib import Path
import re
import unicodedata

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


COLOR_SYNONYMS = {
    "GRIS CEMENTO": "CEMENTO",
    "GRIS RATA": "RATA",
    "AZUL MEDIO": "AZUL M",
    "COLONIAL B": "COLONIAL BLUE",
    "BURGUNDI": "BURGUNDY",
    "BOTELLA": "VERDE BOTELLA",
    "VERDE M": "VERDE MILITAR",
    "JASPE M": "JASPE MEDIO",
    "MENTA BB": "MENTA BEBE",
    "TOFE": "TOFFE",
    "ROSASO VIVO": "ROSADO VIVO",
}


def normalize_text(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)

    return text.upper().strip()


def normalize_color(value) -> str:
    color = normalize_text(value)
    return COLOR_SYNONYMS.get(color, color)


def clean_reference(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    digits = re.sub(r"\D", "", text)

    if not digits:
        return ""

    # Product references are 6 digits. This keeps references like 10101 as 010101.
    if len(digits) <= 6:
        return digits.zfill(6)

    return digits


def to_number(value):
    if pd.isna(value):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    negative = text.startswith("(") or text.endswith(")")
    text = text.replace("(", "").replace(")", "").replace(",", "")
    text = re.sub(r"[^0-9.\-]", "", text)

    if text in {"", "-", "."}:
        return None

    try:
        number = float(text)
        return -abs(number) if negative else number
    except ValueError:
        return None


def find_sales_files() -> list[Path]:
    files = [
        path
        for path in EXTRACTED_DIR.glob("**/sales/*")
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"}
    ]

    if not files:
        raise FileNotFoundError(
            "No sales Excel files found. Expected files inside data/extracted/**/sales/."
        )

    return sorted(files)


def find_header_row(raw_df: pd.DataFrame) -> int:
    for idx, row in raw_df.iterrows():
        values = [normalize_text(value) for value in row.tolist()]

        if "REF" in values and "KILOS" in values:
            return idx

    raise ValueError("Could not find sales header row with REF and KILOS.")


def extract_period(raw_df: pd.DataFrame) -> tuple[str, str]:
    """
    Finds text like:
    01/01/2026 al 31/01/2026
    """

    header_text = " ".join(
        str(value)
        for value in raw_df.head(15).values.ravel()
        if pd.notna(value)
    )

    match = re.search(
        r"(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})",
        header_text,
        flags=re.IGNORECASE,
    )

    if not match:
        raise ValueError("Could not extract sales period from report header.")

    start_date = pd.to_datetime(match.group(1), dayfirst=True)
    end_date = pd.to_datetime(match.group(2), dayfirst=True)

    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def parse_sales_file(file_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_df = pd.read_excel(file_path, sheet_name=0, header=None, dtype=object)

    header_row = find_header_row(raw_df)
    period_start, period_end = extract_period(raw_df)

    df = pd.read_excel(file_path, sheet_name=0, header=header_row, dtype=object)
    df.columns = [str(col).strip() for col in df.columns]

    df = df.rename(
        columns={
            "REF": "reference",
            "NOMBRE REF": "description",
            "COLOR": "color_original",
            "#Rollos": "roll_count",
            "KILOS": "kilos",
            "Subtotal": "subtotal",
        }
    )

    required_columns = [
        "reference",
        "description",
        "color_original",
        "roll_count",
        "kilos",
        "subtotal",
    ]

    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        raise ValueError(f"Missing columns in {file_path.name}: {missing_columns}")

    df["source_file"] = file_path.name
    df["source_sheet"] = "Hoja1"
    df["source_row"] = df.index + header_row + 2

    df["period_start"] = period_start
    df["period_end"] = period_end
    df["movement_date"] = period_end
    df["movement_month"] = period_end[:7]

    df["reference"] = df["reference"].apply(clean_reference)
    df["description"] = df["description"].apply(normalize_text)
    df["color_original"] = df["color_original"].apply(normalize_text)
    df["color_normalized"] = df["color_original"].apply(normalize_color)
    df["product_key"] = df["reference"] + "|" + df["color_normalized"]

    df["roll_count"] = df["roll_count"].apply(to_number)
    df["kilos"] = df["kilos"].apply(to_number)
    df["subtotal"] = df["subtotal"].apply(to_number)

    # Keep only real sales detail rows.
    # This removes report titles, separators, product subtotals and grand totals.
    detail = df[
        df["reference"].str.match(r"^\d{6}$", na=False)
        & (df["description"] != "")
        & (df["color_original"] != "")
        & df["kilos"].notna()
    ].copy()

    quality_rows = []

    # Negative KILOS are kept as stock-in returns/adjustments, but flagged.
    negative_rows = detail[detail["kilos"] < 0].copy()

    if not negative_rows.empty:
        negative_rows["issue_type"] = "NEGATIVE_SALES_QUANTITY_TREATED_AS_RETURN_OR_ADJUSTMENT"
        negative_rows["issue_detail"] = "KILOS is negative. Counted as inventory increase, but should be reviewed."
        quality_rows.append(negative_rows)

    # Zero KILOS should not affect inventory, but may indicate corrections or report anomalies.
    zero_rows = detail[detail["kilos"] == 0].copy()

    if not zero_rows.empty:
        zero_rows["issue_type"] = "ZERO_SALES_QUANTITY"
        zero_rows["issue_detail"] = "KILOS is zero. Not counted as stock movement."
        quality_rows.append(zero_rows)

    movements_source = detail[detail["kilos"] != 0].copy()

    movements_source["movement_type"] = movements_source["kilos"].apply(
        lambda qty: "SALE" if qty > 0 else "SALES_RETURN_OR_ADJUSTMENT"
    )

    movements_source["qty_in"] = movements_source["kilos"].apply(
        lambda qty: abs(qty) if qty < 0 else 0.0
    )

    movements_source["qty_out"] = movements_source["kilos"].apply(
        lambda qty: qty if qty > 0 else 0.0
    )

    movements_source["net_qty"] = movements_source["qty_in"] - movements_source["qty_out"]

    movements_source["document"] = (
        "SALES_REPORT_"
        + movements_source["movement_month"].str.replace("-", "_", regex=False)
    )

    movements_source["lot"] = ""
    movements_source["roll"] = ""
    movements_source["lotrol"] = ""
    movements_source["location"] = ""
    movements_source["unit_of_measure"] = "KG"
    movements_source["validation_status"] = movements_source["movement_type"].apply(
        lambda movement_type: "OK" if movement_type == "SALE" else "REVIEW_RETURN_OR_ADJUSTMENT"
    )

    movement_columns = [
        "movement_date",
        "movement_month",
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
        "period_start",
        "period_end",
        "roll_count",
        "subtotal",
    ]

    movements = movements_source[movement_columns].copy()

    if quality_rows:
        quality = pd.concat(quality_rows, ignore_index=True)

        quality_columns = [
            "issue_type",
            "issue_detail",
            "period_start",
            "period_end",
            "reference",
            "description",
            "color_original",
            "color_normalized",
            "product_key",
            "roll_count",
            "kilos",
            "subtotal",
            "source_file",
            "source_sheet",
            "source_row",
        ]

        quality = quality[quality_columns].copy()
    else:
        quality = pd.DataFrame()

    return movements, quality


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    sales_files = find_sales_files()

    all_movements = []
    all_quality = []

    print(f"Found {len(sales_files)} sales files.")

    for file_path in sales_files:
        print(f"Reading sales file: {file_path.name}")

        movements, quality = parse_sales_file(file_path)

        all_movements.append(movements)

        if not quality.empty:
            all_quality.append(quality)

        print(
            f"  Movements: {len(movements):,} | "
            f"Net qty: {movements['net_qty'].sum():,.2f} | "
            f"Quality rows: {len(quality):,}"
        )

    sales_movements = pd.concat(all_movements, ignore_index=True)

    if all_quality:
        sales_quality = pd.concat(all_quality, ignore_index=True)
    else:
        sales_quality = pd.DataFrame()

    summary = (
        sales_movements.groupby(
            [
                "movement_month",
                "reference",
                "description",
                "color_normalized",
                "product_key",
            ],
            as_index=False,
        )
        .agg(
            sales_qty=("qty_out", "sum"),
            returns_adjustments_qty=("qty_in", "sum"),
            net_qty=("net_qty", "sum"),
            movement_rows=("net_qty", "size"),
            subtotal=("subtotal", "sum"),
        )
        .sort_values(["movement_month", "reference", "color_normalized"])
    )

    movements_path = PROCESSED_DIR / "sales_stock_movements.csv"
    summary_path = PROCESSED_DIR / "sales_summary_by_month_product.csv"
    quality_path = PROCESSED_DIR / "sales_quality_checks.csv"

    sales_movements.to_csv(movements_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    sales_quality.to_csv(quality_path, index=False, encoding="utf-8-sig")

    print("Done.")
    print(f"Total sales movement rows: {len(sales_movements):,}")
    print(f"Total qty out / sales: {sales_movements['qty_out'].sum():,.2f}")
    print(f"Total qty in / returns-adjustments: {sales_movements['qty_in'].sum():,.2f}")
    print(f"Net inventory impact: {sales_movements['net_qty'].sum():,.2f}")
    print(f"Quality check rows: {len(sales_quality):,}")
    print(f"Wrote: {movements_path}")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {quality_path}")


if __name__ == "__main__":
    main()