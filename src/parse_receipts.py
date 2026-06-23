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
    text = text.replace("\xa0", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)

    return text.upper().strip()


def normalize_color(value) -> str:
    color = normalize_text(value)
    return COLOR_SYNONYMS.get(color, color)


def normalize_ibum_id(value) -> str:
    ibum_id = normalize_text(value)
    return re.sub(r"\s+", "", ibum_id)


def clean_reference(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    digits = re.sub(r"\D", "", text)

    if not digits:
        return ""

    if len(digits) <= 6:
        return digits.zfill(6)

    return digits


def clean_code(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    return text.strip()


def to_number(value):
    if pd.isna(value):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    negative = text.startswith("(") or text.endswith(")")
    text = text.replace("(", "").replace(")", "")
    text = text.replace(",", "")
    text = re.sub(r"[^0-9.\-]", "", text)

    if text in {"", "-", "."}:
        return None

    try:
        number = float(text)
        return -abs(number) if negative else number
    except ValueError:
        return None


def find_receipt_files() -> list[Path]:
    files = [
        path
        for path in EXTRACTED_DIR.glob("**/inventory-receipts/*")
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"}
    ]

    if not files:
        raise FileNotFoundError(
            "No receipt Excel files found. Expected files inside data/extracted/**/inventory-receipts/."
        )

    return sorted(files)


def find_ibum_sheet(sheet_names: list[str]) -> str | None:
    normalized = {sheet_name: normalize_text(sheet_name) for sheet_name in sheet_names}

    for sheet_name, clean_name in normalized.items():
        if clean_name == "IBUM":
            return sheet_name

    for sheet_name, clean_name in normalized.items():
        if "IBUM" in clean_name:
            return sheet_name

    return None


def extract_ibum_id(excel: pd.ExcelFile, file_path: Path) -> tuple[str, str, pd.DataFrame]:
    quality_columns = [
        "issue_type",
        "issue_detail",
        "movement_date",
        "movement_month",
        "reference",
        "description",
        "color_code",
        "color_original",
        "color_normalized",
        "product_key",
        "lot",
        "roll",
        "lotrol",
        "ibum_id",
        "container_key",
        "weight",
        "entrada",
        "salida",
        "asignacion",
        "saldo",
        "source_file",
        "source_sheet",
        "source_row",
    ]

    ibum_sheet = find_ibum_sheet(excel.sheet_names)
    ibum_id = ""

    if ibum_sheet is not None:
        try:
            ibum_raw = pd.read_excel(
                file_path,
                sheet_name=ibum_sheet,
                header=None,
                dtype=object,
                nrows=1,
                usecols=[0],
            )

            if not ibum_raw.empty:
                ibum_id = normalize_ibum_id(ibum_raw.iat[0, 0])
        except Exception:
            ibum_id = ""

    container_key = ibum_id if ibum_id else f"MISSING_IBUM::{file_path.name}"

    if ibum_id:
        return ibum_id, container_key, pd.DataFrame(columns=quality_columns)

    missing_quality = pd.DataFrame(
        [
            {
                "issue_type": "MISSING_IBUM_ID",
                "issue_detail": "Receipt workbook does not contain IBUM sheet or IBUM!A1 is empty.",
                "movement_date": "",
                "movement_month": "",
                "reference": "",
                "description": "",
                "color_code": "",
                "color_original": "",
                "color_normalized": "",
                "product_key": "",
                "lot": "",
                "roll": "",
                "lotrol": "",
                "ibum_id": "",
                "container_key": container_key,
                "weight": "",
                "entrada": "",
                "salida": "",
                "asignacion": "",
                "saldo": "",
                "source_file": file_path.name,
                "source_sheet": ibum_sheet or "",
                "source_row": 1 if ibum_sheet else "",
            }
        ],
        columns=quality_columns,
    )

    return ibum_id, container_key, missing_quality


def find_header_row(raw_df: pd.DataFrame) -> int:
    for idx, row in raw_df.iterrows():
        values = [normalize_text(value) for value in row.tolist()]

        if "REFERENCIA" in values and "LOTROL" in values and "ENTRADA" in values:
            return idx

    raise ValueError("Could not find receipt header row with REFERENCIA, LOTROL and ENTRADA.")


def extract_report_date(raw_df: pd.DataFrame, file_path: Path) -> str:
    """
    Most receipt reports have the date near the top, usually in row 3 / first column.
    If the report date cannot be found, we fall back to a date guessed from the file name.
    """

    # First, inspect top cells.
    for value in raw_df.head(10).values.ravel():
        if pd.isna(value):
            continue

        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")

        if pd.notna(parsed):
            # Avoid weird dates accidentally parsed from numbers.
            if parsed.year >= 2025:
                return parsed.strftime("%Y-%m-%d")

        text = str(value)
        match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)

        if match:
            parsed = pd.to_datetime(match.group(1), dayfirst=True, errors="coerce")

            if pd.notna(parsed):
                return parsed.strftime("%Y-%m-%d")

    # Fallback from file name.
    # This is intentionally conservative; if it fails, we flag the date.
    month_map = {
        "ENERO": "01",
        "FEBRERO": "02",
        "MARZO": "03",
        "ABRIL": "04",
        "MAYO": "05",
        "JUNIO": "06",
        "JULIO": "07",
        "AGOSTO": "08",
        "SEPTIEMBRE": "09",
        "SETIEMBRE": "09",
        "OCTUBRE": "10",
        "NOVIEMBRE": "11",
        "DICIEMBRE": "12",
    }

    file_name = normalize_text(file_path.stem)

    for month_name, month_number in month_map.items():
        if month_name in file_name:
            day_match = re.search(r"(\d{1,2})", file_name)

            if day_match:
                day = int(day_match.group(1))
                return f"2026-{month_number}-{day:02d}"

    return ""


def parse_receipt_sheet(
    file_path: Path,
    sheet_name: str,
    ibum_id: str,
    container_key: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=object)

    header_row = find_header_row(raw_df)
    report_date = extract_report_date(raw_df, file_path)
    movement_month = report_date[:7] if report_date else ""

    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, dtype=object)
    df.columns = [str(col).strip() for col in df.columns]

    df = df.rename(
        columns={
            "REFERENCIA": "reference",
            "NOMBRE": "description",
            "COLOR": "color_code",
            "NONCOLOR": "color_original",
            "LOTE": "lot",
            "Rollo": "roll",
            "ROLLO": "roll",
            "LOTROL": "lotrol",
            "PESO": "weight",
            "ENTRADA": "entrada",
            "SALIDA": "salida",
            "ASIGNACION": "asignacion",
            "SALDO": "saldo",
        }
    )

    required_columns = [
        "reference",
        "description",
        "color_code",
        "color_original",
        "lot",
        "roll",
        "lotrol",
        "weight",
        "entrada",
        "salida",
        "asignacion",
        "saldo",
    ]

    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        raise ValueError(f"Missing columns in {file_path.name} / {sheet_name}: {missing_columns}")

    df["source_file"] = file_path.name
    df["source_sheet"] = sheet_name
    df["source_row"] = df.index + header_row + 2
    df["ibum_id"] = ibum_id
    df["container_key"] = container_key

    df["movement_date"] = report_date
    df["movement_month"] = movement_month

    df["reference"] = df["reference"].apply(clean_reference)
    df["description"] = df["description"].apply(normalize_text)
    df["color_code"] = df["color_code"].apply(clean_code)
    df["color_original"] = df["color_original"].apply(normalize_text)
    df["color_normalized"] = df["color_original"].apply(normalize_color)
    df["product_key"] = df["reference"] + "|" + df["color_normalized"]

    df["lot"] = df["lot"].apply(clean_code)
    df["roll"] = df["roll"].apply(clean_code)
    df["lotrol"] = df["lotrol"].apply(clean_code)

    df["weight"] = df["weight"].apply(to_number)
    df["entrada"] = df["entrada"].apply(to_number)
    df["salida"] = df["salida"].apply(to_number)
    df["asignacion"] = df["asignacion"].apply(to_number)
    df["saldo"] = df["saldo"].apply(to_number)

    detail = df[
        df["reference"].str.match(r"^\d{6}$", na=False)
        & (df["description"] != "")
        & (df["color_original"] != "")
        & (df["lotrol"] != "")
        & df["entrada"].notna()
        & (df["entrada"] != 0)
    ].copy()

    detail["movement_type"] = "CONTAINER_RECEIPT"
    detail["load_id"] = "LOCAL_RUN"
    detail["movement_group"] = "IMPORT"
    detail["movement_subtype"] = "CONTAINER_RECEIPT"
    detail["traceability_level"] = "ROLL"
    detail["document"] = "RECEIPT_" + detail["movement_month"].str.replace("-", "_", regex=False)
    detail["location"] = ""
    detail["qty_in"] = detail["entrada"]
    detail["qty_out"] = 0.0
    detail["net_qty"] = detail["entrada"]
    detail["unit_of_measure"] = "KG"
    detail["validation_status"] = "OK"

    quality_rows = []

    if report_date == "":
        no_date = detail.copy()
        no_date["issue_type"] = "MISSING_RECEIPT_DATE"
        no_date["issue_detail"] = "Could not determine receipt report date."
        quality_rows.append(no_date)

    has_salida = detail[detail["salida"].fillna(0) != 0].copy()

    if not has_salida.empty:
        has_salida["issue_type"] = "RECEIPT_REPORT_HAS_SALIDA"
        has_salida["issue_detail"] = "Receipt report has SALIDA values. Use ENTRADA as receipt, but review because report is not a pure import document."
        quality_rows.append(has_salida)

    has_asignacion = detail[detail["asignacion"].fillna(0) != 0].copy()

    if not has_asignacion.empty:
        has_asignacion["issue_type"] = "RECEIPT_REPORT_HAS_ASIGNACION"
        has_asignacion["issue_detail"] = "Receipt report has ASIGNACION values. Review operational meaning."
        quality_rows.append(has_asignacion)

    movement_columns = [
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
        "weight",
        "entrada",
        "salida",
        "asignacion",
        "saldo",
    ]

    movements = detail[movement_columns].copy()

    quality_columns = [
        "issue_type",
        "issue_detail",
        "movement_date",
        "movement_month",
        "reference",
        "description",
        "color_code",
        "color_original",
        "color_normalized",
        "product_key",
        "lot",
        "roll",
        "lotrol",
        "ibum_id",
        "container_key",
        "weight",
        "entrada",
        "salida",
        "asignacion",
        "saldo",
        "source_file",
        "source_sheet",
        "source_row",
    ]

    if quality_rows:
        quality = pd.concat(quality_rows, ignore_index=True)
        quality = quality[quality_columns].copy()
    else:
        quality = pd.DataFrame(columns=quality_columns)

    return movements, quality


def parse_receipt_file(file_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        excel = pd.ExcelFile(file_path)
    except ImportError as exc:
        raise ImportError(
            "Could not read an Excel receipt file. If this is an .xls file, run: pip install xlrd"
        ) from exc

    all_movements = []
    all_quality = []
    ibum_id, container_key, ibum_quality = extract_ibum_id(excel, file_path)

    if not ibum_quality.empty:
        all_quality.append(ibum_quality)

    ibum_sheet = find_ibum_sheet(excel.sheet_names)

    for sheet_name in excel.sheet_names:
        if ibum_sheet is not None and sheet_name == ibum_sheet:
            continue

        try:
            movements, quality = parse_receipt_sheet(
                file_path,
                sheet_name,
                ibum_id=ibum_id,
                container_key=container_key,
            )
            all_movements.append(movements)

            if not quality.empty:
                all_quality.append(quality)

        except ValueError as exc:
            print(f"  Skipping sheet {sheet_name} in {file_path.name}: {exc}")

    if not all_movements:
        raise ValueError(f"No valid receipt sheets found in {file_path.name}")

    movements = pd.concat(all_movements, ignore_index=True)

    if all_quality:
        quality = pd.concat(all_quality, ignore_index=True)
    else:
        quality = pd.DataFrame()

    return movements, quality


def build_duplicate_lotrol_report(raw_movements: pd.DataFrame) -> pd.DataFrame:
    duplicates = raw_movements[
        raw_movements.duplicated("lotrol", keep=False)
    ].copy()

    if duplicates.empty:
        return pd.DataFrame()

    duplicates = duplicates.sort_values(
        ["lotrol", "movement_date", "source_file", "source_row"]
    ).copy()

    duplicates["duplicate_occurrence_number"] = duplicates.groupby("lotrol").cumcount() + 1
    duplicates["should_count_in_inventory"] = duplicates["duplicate_occurrence_number"] == 1
    duplicates["duplicate_qty_excluded"] = duplicates.apply(
        lambda row: 0.0 if row["should_count_in_inventory"] else row["qty_in"],
        axis=1,
    )

    duplicate_counts = (
        duplicates.groupby("lotrol", as_index=False)
        .agg(
            duplicate_occurrences=("lotrol", "size"),
            duplicated_total_qty=("qty_in", "sum"),
            excluded_duplicate_qty=("duplicate_qty_excluded", "sum"),
            files=("source_file", lambda values: " | ".join(sorted(set(values)))),
        )
    )

    duplicates = duplicates.merge(
        duplicate_counts,
        on="lotrol",
        how="left",
    )

    duplicate_columns = [
        "lotrol",
        "ibum_id",
        "container_key",
        "duplicate_occurrences",
        "duplicate_occurrence_number",
        "should_count_in_inventory",
        "duplicate_qty_excluded",
        "excluded_duplicate_qty",
        "duplicated_total_qty",
        "files",
        "movement_date",
        "movement_month",
        "reference",
        "description",
        "color_code",
        "color_original",
        "color_normalized",
        "product_key",
        "lot",
        "roll",
        "qty_in",
        "source_file",
        "source_sheet",
        "source_row",
    ]

    return duplicates[duplicate_columns].copy()


def deduplicate_receipts(raw_movements: pd.DataFrame) -> pd.DataFrame:
    official = raw_movements.sort_values(
        ["lotrol", "movement_date", "source_file", "source_row"]
    ).copy()

    official = official.drop_duplicates("lotrol", keep="first").copy()

    return official.sort_values(
        ["movement_date", "source_file", "source_row"]
    ).reset_index(drop=True)


def join_unique(values: pd.Series) -> str:
    clean_values = [
        str(value).strip()
        for value in values
        if not pd.isna(value) and str(value).strip()
    ]

    return " | ".join(sorted(set(clean_values)))


def build_container_import_summary(
    official_movements: pd.DataFrame,
    duplicate_lotrols: pd.DataFrame,
) -> pd.DataFrame:
    group_cols = [
        "container_key",
        "ibum_id",
        "reference",
        "description",
        "color_original",
        "color_normalized",
        "product_key",
    ]

    summary = (
        official_movements.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            source_files=("source_file", join_unique),
            movement_months=("movement_month", join_unique),
            receipt_qty=("qty_in", "sum"),
            roll_count=("qty_in", "size"),
            unique_lotrols=("lotrol", "nunique"),
        )
    )

    if duplicate_lotrols.empty:
        excluded = pd.DataFrame(columns=group_cols + ["duplicate_lotrols_excluded"])
    else:
        excluded_source = duplicate_lotrols[
            duplicate_lotrols["should_count_in_inventory"].astype(str).str.upper() != "TRUE"
        ].copy()

        if excluded_source.empty:
            excluded = pd.DataFrame(columns=group_cols + ["duplicate_lotrols_excluded"])
        else:
            excluded = (
                excluded_source.groupby(group_cols, dropna=False, as_index=False)
                .agg(duplicate_lotrols_excluded=("lotrol", "nunique"))
            )

    summary = summary.merge(excluded, on=group_cols, how="left")
    summary["duplicate_lotrols_excluded"] = summary["duplicate_lotrols_excluded"].fillna(0).astype(int)

    summary["validation_status"] = "OK"
    summary.loc[summary["ibum_id"].fillna("").astype(str).str.strip() == "", "validation_status"] = "WARNING_MISSING_IBUM"
    summary.loc[
        (summary["validation_status"] == "OK")
        & (summary["duplicate_lotrols_excluded"] > 0),
        "validation_status",
    ] = "REVIEW_DUPLICATE_LOTROL"
    summary.loc[
        (summary["validation_status"] == "WARNING_MISSING_IBUM")
        & (summary["duplicate_lotrols_excluded"] > 0),
        "validation_status",
    ] = "WARNING_MISSING_IBUM_AND_DUPLICATES"

    ordered_cols = [
        "container_key",
        "ibum_id",
        "source_files",
        "movement_months",
        "reference",
        "description",
        "color_original",
        "color_normalized",
        "product_key",
        "receipt_qty",
        "roll_count",
        "unique_lotrols",
        "duplicate_lotrols_excluded",
        "validation_status",
    ]

    return summary[ordered_cols].sort_values(
        ["container_key", "reference", "color_normalized"]
    )


def build_container_import_header(
    official_movements: pd.DataFrame,
    duplicate_lotrols: pd.DataFrame,
) -> pd.DataFrame:
    group_cols = ["container_key", "ibum_id"]

    header = (
        official_movements.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            source_files=("source_file", join_unique),
            first_movement_date=("movement_date", "min"),
            last_movement_date=("movement_date", "max"),
            first_movement_month=("movement_month", "min"),
            last_movement_month=("movement_month", "max"),
            total_receipt_qty=("qty_in", "sum"),
            unique_references=("reference", "nunique"),
            unique_product_keys=("product_key", "nunique"),
            unique_colors=("color_normalized", "nunique"),
            unique_lotrols=("lotrol", "nunique"),
            source_file_count=("source_file", "nunique"),
        )
    )

    if duplicate_lotrols.empty:
        duplicate_header = pd.DataFrame(
            columns=group_cols + ["duplicate_lotrol_count", "duplicate_qty_excluded"]
        )
    else:
        excluded_source = duplicate_lotrols[
            duplicate_lotrols["should_count_in_inventory"].astype(str).str.upper() != "TRUE"
        ].copy()

        if excluded_source.empty:
            duplicate_header = pd.DataFrame(
                columns=group_cols + ["duplicate_lotrol_count", "duplicate_qty_excluded"]
            )
        else:
            duplicate_header = (
                excluded_source.groupby(group_cols, dropna=False, as_index=False)
                .agg(
                    duplicate_lotrol_count=("lotrol", "nunique"),
                    duplicate_qty_excluded=("duplicate_qty_excluded", "sum"),
                )
            )

    header = header.merge(duplicate_header, on=group_cols, how="left")
    header["duplicate_lotrol_count"] = header["duplicate_lotrol_count"].fillna(0).astype(int)
    header["duplicate_qty_excluded"] = header["duplicate_qty_excluded"].fillna(0.0)
    header["has_missing_ibum"] = header["ibum_id"].fillna("").astype(str).str.strip() == ""

    header["validation_status"] = "OK"
    header.loc[header["has_missing_ibum"], "validation_status"] = "WARNING_MISSING_IBUM"
    header.loc[
        (~header["has_missing_ibum"])
        & (header["duplicate_lotrol_count"] > 0),
        "validation_status",
    ] = "REVIEW_DUPLICATE_LOTROL"
    header.loc[
        header["has_missing_ibum"]
        & (header["duplicate_lotrol_count"] > 0),
        "validation_status",
    ] = "WARNING_MISSING_IBUM_AND_DUPLICATES"

    ordered_cols = [
        "container_key",
        "ibum_id",
        "source_files",
        "first_movement_date",
        "last_movement_date",
        "first_movement_month",
        "last_movement_month",
        "total_receipt_qty",
        "unique_references",
        "unique_product_keys",
        "unique_colors",
        "unique_lotrols",
        "duplicate_lotrol_count",
        "duplicate_qty_excluded",
        "source_file_count",
        "has_missing_ibum",
        "validation_status",
    ]

    return header[ordered_cols].sort_values(["first_movement_month", "container_key"])


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    receipt_files = find_receipt_files()

    all_movements = []
    all_quality = []

    print(f"Found {len(receipt_files)} receipt files.")

    for file_path in receipt_files:
        print(f"Reading receipt file: {file_path.name}")

        movements, quality = parse_receipt_file(file_path)

        all_movements.append(movements)

        if not quality.empty:
            all_quality.append(quality)

        print(
            f"  Rows: {len(movements):,} | "
            f"Qty in: {movements['qty_in'].sum():,.2f} | "
            f"Quality rows: {len(quality):,}"
        )

    raw_movements = pd.concat(all_movements, ignore_index=True)

    duplicate_lotrols = build_duplicate_lotrol_report(raw_movements)
    official_movements = deduplicate_receipts(raw_movements)
    container_summary = build_container_import_summary(official_movements, duplicate_lotrols)
    container_header = build_container_import_header(official_movements, duplicate_lotrols)

    if all_quality:
        receipts_quality = pd.concat(all_quality, ignore_index=True)
    else:
        receipts_quality = pd.DataFrame()

    if not duplicate_lotrols.empty:
        duplicate_quality = duplicate_lotrols.copy()
        duplicate_quality["issue_type"] = "DUPLICATE_LOTROL"
        duplicate_quality["issue_detail"] = "Same LOTROL appears in more than one receipt row. Only first occurrence is counted in official movements."

        duplicate_quality = duplicate_quality[
            [
                "issue_type",
                "issue_detail",
                "movement_date",
                "movement_month",
                "reference",
                "description",
                "color_code",
                "color_original",
                "color_normalized",
                "product_key",
                "lot",
                "roll",
                "lotrol",
                "ibum_id",
                "container_key",
                "qty_in",
                "duplicate_occurrence_number",
                "should_count_in_inventory",
                "duplicate_qty_excluded",
                "excluded_duplicate_qty",
                "source_file",
                "source_sheet",
                "source_row",
            ]
        ].copy()

        receipts_quality = pd.concat(
            [receipts_quality, duplicate_quality],
            ignore_index=True,
        )

    summary = (
        official_movements.groupby(
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
            receipt_qty=("qty_in", "sum"),
            receipt_rows=("qty_in", "size"),
            unique_lotrols=("lotrol", "nunique"),
        )
        .sort_values(["movement_month", "reference", "color_normalized"])
    )

    raw_path = PROCESSED_DIR / "receipt_stock_movements_raw.csv"
    official_path = PROCESSED_DIR / "receipt_stock_movements.csv"
    summary_path = PROCESSED_DIR / "receipt_summary_by_month_product.csv"
    duplicate_path = PROCESSED_DIR / "duplicate_lotrols.csv"
    quality_path = PROCESSED_DIR / "receipts_quality_checks.csv"
    container_summary_path = PROCESSED_DIR / "container_import_summary.csv"
    container_header_path = PROCESSED_DIR / "container_import_header.csv"

    raw_movements.to_csv(raw_path, index=False, encoding="utf-8-sig")
    official_movements.to_csv(official_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    duplicate_lotrols.to_csv(duplicate_path, index=False, encoding="utf-8-sig")
    receipts_quality.to_csv(quality_path, index=False, encoding="utf-8-sig")
    container_summary.to_csv(container_summary_path, index=False, encoding="utf-8-sig")
    container_header.to_csv(container_header_path, index=False, encoding="utf-8-sig")

    raw_qty = raw_movements["qty_in"].sum()
    official_qty = official_movements["qty_in"].sum()
    duplicate_excluded_qty = raw_qty - official_qty

    print("Done.")
    print(f"Raw receipt rows: {len(raw_movements):,}")
    print(f"Official deduplicated receipt rows: {len(official_movements):,}")
    print(f"Raw receipt qty: {raw_qty:,.2f}")
    print(f"Official deduplicated receipt qty: {official_qty:,.2f}")
    print(f"Duplicate LOTROL values: {duplicate_lotrols['lotrol'].nunique() if not duplicate_lotrols.empty else 0:,}")
    print(f"Duplicate qty excluded: {duplicate_excluded_qty:,.2f}")
    print(f"Quality check rows: {len(receipts_quality):,}")
    print(f"Container summary rows: {len(container_summary):,}")
    print(f"Container header rows: {len(container_header):,}")
    print(f"Wrote: {raw_path}")
    print(f"Wrote: {official_path}")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {duplicate_path}")
    print(f"Wrote: {quality_path}")
    print(f"Wrote: {container_summary_path}")
    print(f"Wrote: {container_header_path}")


if __name__ == "__main__":
    main()
