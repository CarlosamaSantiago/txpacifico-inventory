from pathlib import Path
import re
import unicodedata

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

OPENING_DATE = "2025-12-31"
OPENING_MONTH = "2025-12"


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

    text = re.sub(r"\D", "", text)

    return text.zfill(6) if text else ""


def clean_lotrol(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    return text


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


def find_opening_inventory_file() -> Path:
    candidates = list(EXTRACTED_DIR.glob("**/INVENTARIO*31122025*.xlsx"))

    if not candidates:
        raise FileNotFoundError(
            "Could not find opening inventory file. "
            "Expected something like INVENTARIO 31122025.xlsx inside data/extracted/."
        )

    return candidates[0]


def parse_cop_sheet(file_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_excel(file_path, sheet_name="COP", header=4, dtype=object)

    # Some column names have weird spaces, for example "    FISICO"
    df.columns = [str(col).strip() for col in df.columns]

    df = df.rename(
        columns={
            "LL": "reference",
            "Nombre": "description",
            "FISICO": "physical_qty",
            "INVEN": "system_qty",
            "DIFEREN": "difference_qty",
            "LOTE": "lotrol",
            "Color": "color_code",
            "NOM_COLOR": "color_original",
            "Talla": "size",
            "UBICAC.": "location",
            "FECP": "stock_date_original",
        }
    )

    df["reference"] = df["reference"].apply(clean_reference)
    df["physical_qty"] = df["physical_qty"].apply(to_number)
    df["system_qty"] = df["system_qty"].apply(to_number)

    # Keep only real product rows
    df = df[df["reference"].str.match(r"^\d{6}$", na=False)].copy()
    df = df[df["physical_qty"].notna()].copy()

    df["description"] = df["description"].apply(normalize_text)
    df["color_original"] = df["color_original"].apply(normalize_text)
    df["color_normalized"] = df["color_original"].apply(normalize_color)
    df["product_key"] = df["reference"] + "|" + df["color_normalized"]
    df["lotrol"] = df["lotrol"].apply(clean_lotrol)

    # Excel row number: header is row 5, first data row is row 6
    df["source_row"] = df.index + 6

    movements = pd.DataFrame(
        {
            "movement_date": OPENING_DATE,
            "movement_month": OPENING_MONTH,
            "movement_type": "OPENING_PHYSICAL_ROLL",
            "load_id": "LOCAL_RUN",
            "ibum_id": "",
            "container_key": "",
            "movement_group": "OPENING",
            "movement_subtype": "PHYSICAL_ROLL",
            "traceability_level": "ROLL",
            "document": "INVENTARIO_31122025_COP",
            "reference": df["reference"],
            "description": df["description"],
            "color_original": df["color_original"],
            "color_normalized": df["color_normalized"],
            "product_key": df["product_key"],
            "lot": "",
            "roll": "",
            "lotrol": df["lotrol"],
            "location": df["location"].fillna("").astype(str).str.strip(),
            "qty_in": df["physical_qty"],
            "qty_out": 0.0,
            "net_qty": df["physical_qty"],
            "unit_of_measure": "KG",
            "source_file": file_path.name,
            "source_sheet": "COP",
            "source_row": df["source_row"],
            "validation_status": "OK",
        }
    )

    quality = df.copy()
    quality["physical_minus_system"] = quality["physical_qty"] - quality["system_qty"]

    quality = quality[quality["physical_minus_system"].abs() > 0.001]

    quality = quality[
        [
            "reference",
            "description",
            "color_original",
            "color_normalized",
            "lotrol",
            "location",
            "physical_qty",
            "system_qty",
            "physical_minus_system",
            "source_row",
        ]
    ]

    quality["issue_type"] = "OPENING_PHYSICAL_DIFFERS_FROM_SYSTEM"

    return movements, quality


def parse_rib_cuellos_sheet(file_path: Path) -> pd.DataFrame:
    excel = pd.ExcelFile(file_path)

    sheet_name = next(
        (sheet for sheet in excel.sheet_names if "RIB Y CUELLOS" in sheet.upper()),
        None,
    )

    if sheet_name is None:
        raise ValueError("Could not find RIB Y CUELLOS sheet.")

    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=object)

    rows = []

    # These references were mapped from the product blocks in the sheet
    rib_blocks = [
        ("010201", "RIB PERUANO 200", 1, 2),
        ("010202", "RIB PERUANO 250", 4, 5),
        ("010204", "RIB PERUANO 150", 7, 8),
        ("010206", "RIB PERUANO 310", 10, 11),
        ("050201", "RIB BURDA", 13, 14),
        ("020201", "RIB F200", 16, 17),
        ("020202", "RIB F240", 19, 20),
    ]

    for reference, description, color_col, qty_col in rib_blocks:
        for idx in range(3, 24):
            color = normalize_text(raw.iat[idx, color_col]) if color_col < raw.shape[1] else ""
            qty = to_number(raw.iat[idx, qty_col]) if qty_col < raw.shape[1] else None

            if color and qty is not None and qty != 0:
                rows.append(
                    {
                        "movement_date": OPENING_DATE,
                        "movement_month": OPENING_MONTH,
                        "movement_type": "OPENING_RIB_COLLAR_AGG",
                        "load_id": "LOCAL_RUN",
                        "ibum_id": "",
                        "container_key": "",
                        "movement_group": "OPENING",
                        "movement_subtype": "RIB_COLLAR_AGG",
                        "traceability_level": "AGGREGATE",
                        "document": "INVENTARIO_31122025_RIB_Y_CUELLOS",
                        "reference": reference,
                        "description": normalize_text(description),
                        "color_original": color,
                        "color_normalized": normalize_color(color),
                        "lot": "",
                        "roll": "",
                        "lotrol": "",
                        "location": "",
                        "qty_in": qty,
                        "qty_out": 0.0,
                        "net_qty": qty,
                        "unit_of_measure": "KG_OR_UNITS_REVIEW",
                        "source_file": file_path.name,
                        "source_sheet": sheet_name.strip(),
                        "source_row": idx + 1,
                        "validation_status": "REVIEW_UNIT_OF_MEASURE",
                    }
                )

    # CUELLOS block
    cuello_products = [
        ("010301", "CUELLO S-M + PUÑO", 3),
        ("010302", "CUELLO L-XL + PUÑO", 4),
    ]

    for idx in range(28, 47):
        color = normalize_text(raw.iat[idx, 2])

        if not color:
            continue

        for reference, description, qty_col in cuello_products:
            qty = to_number(raw.iat[idx, qty_col])

            if qty is not None and qty != 0:
                rows.append(
                    {
                        "movement_date": OPENING_DATE,
                        "movement_month": OPENING_MONTH,
                        "movement_type": "OPENING_RIB_COLLAR_AGG",
                        "load_id": "LOCAL_RUN",
                        "ibum_id": "",
                        "container_key": "",
                        "movement_group": "OPENING",
                        "movement_subtype": "RIB_COLLAR_AGG",
                        "traceability_level": "AGGREGATE",
                        "document": "INVENTARIO_31122025_RIB_Y_CUELLOS",
                        "reference": reference,
                        "description": normalize_text(description),
                        "color_original": color,
                        "color_normalized": normalize_color(color),
                        "lot": "",
                        "roll": "",
                        "lotrol": "",
                        "location": "",
                        "qty_in": qty,
                        "qty_out": 0.0,
                        "net_qty": qty,
                        "unit_of_measure": "KG_OR_UNITS_REVIEW",
                        "source_file": file_path.name,
                        "source_sheet": sheet_name.strip(),
                        "source_row": idx + 1,
                        "validation_status": "REVIEW_UNIT_OF_MEASURE",
                    }
                )

    movements = pd.DataFrame(rows)

    if not movements.empty:
        movements["product_key"] = movements["reference"] + "|" + movements["color_normalized"]

        ordered_cols = [
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

        movements = movements[ordered_cols]

    return movements


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    file_path = find_opening_inventory_file()

    print(f"Reading opening inventory: {file_path}")

    cop_movements, cop_quality = parse_cop_sheet(file_path)
    rib_movements = parse_rib_cuellos_sheet(file_path)

    opening_movements = pd.concat([cop_movements, rib_movements], ignore_index=True)

    summary = (
        opening_movements.groupby(
            ["reference", "description", "color_normalized", "product_key"],
            as_index=False,
        )
        .agg(
            opening_qty=("qty_in", "sum"),
            movement_rows=("qty_in", "size"),
        )
        .sort_values(["reference", "color_normalized"])
    )

    movements_path = PROCESSED_DIR / "opening_stock_movements.csv"
    summary_path = PROCESSED_DIR / "opening_stock_summary_by_product.csv"
    quality_path = PROCESSED_DIR / "opening_stock_quality_checks.csv"

    opening_movements.to_csv(movements_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    cop_quality.to_csv(quality_path, index=False, encoding="utf-8-sig")

    print("Done.")
    print(f"COP movement rows: {len(cop_movements):,}")
    print(f"RIB/CUELLOS movement rows: {len(rib_movements):,}")
    print(f"Total opening movement rows: {len(opening_movements):,}")
    print(f"Total opening quantity: {opening_movements['qty_in'].sum():,.2f}")
    print(f"Quality check rows: {len(cop_quality):,}")
    print(f"Wrote: {movements_path}")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {quality_path}")


if __name__ == "__main__":
    main()
