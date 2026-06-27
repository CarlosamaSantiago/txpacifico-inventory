from __future__ import annotations

import pandas as pd


COLUMN_LABELS_ES = {
    "movement_month": "Periodo",
    "movement_months": "Periodo",
    "movement_date": "Fecha del registro",
    "reference": "Referencia",
    "description": "Descripcion",
    "color_original": "Color",
    "color_normalized": "Color normalizado",
    "display_color": "Color",
    "ibum_id": "IBUM",
    "source_file": "Archivo origen",
    "source_files": "Archivos origen",
    "source_sheet": "Hoja origen",
    "source_row": "Fila origen",
    "lot": "Lote",
    "roll": "Rollo",
    "lotrol": "LOTROL",
    "movement_type": "Tipo de movimiento",
    "qty_in": "Entrada kg",
    "qty_out": "Salida kg",
    "net_qty": "Movimiento neto kg",
    "opening_balance": "Saldo inicial kg",
    "opening_stock_qty": "Inventario inicial kg",
    "imports_qty": "Importaciones kg",
    "sales_qty": "Ventas kg",
    "returns_adjustments_qty": "Devoluciones / ajustes kg",
    "net_change": "Cambio neto kg",
    "closing_balance": "Saldo final kg",
    "receipt_qty": "Cantidad recibida kg",
    "total_receipt_qty": "Kg importados",
    "roll_count": "Cantidad de rollos",
    "unique_references": "Referencias",
    "unique_colors": "Colores",
    "unique_lotrols": "LOTROLs unicos",
    "duplicate_lotrol_count": "LOTROLs duplicados",
    "duplicate_qty_excluded": "Kg duplicados excluidos",
    "duplicate_lotrols_excluded": "LOTROLs duplicados excluidos",
    "source_file_count": "Cantidad de archivos",
    "first_movement_date": "Fecha inicial",
    "last_movement_date": "Fecha final",
    "first_movement_month": "Periodo inicial",
    "last_movement_month": "Periodo final",
    "validation_status": "Estado",
    "issue_type": "Tipo de alerta",
    "issue_detail": "Detalle",
}


def display_color_column(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=str)

    original = (
        df["color_original"].fillna("").astype(str).str.strip()
        if "color_original" in df.columns
        else pd.Series("", index=df.index)
    )
    normalized = (
        df["color_normalized"].fillna("").astype(str).str.strip()
        if "color_normalized" in df.columns
        else pd.Series("", index=df.index)
    )

    return original.where(original.ne(""), normalized)


def format_number(value) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]

    if pd.isna(number):
        return ""

    return f"{float(number):,.2f}"


def format_numeric_columns_for_display(
    df: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    display_df = df.copy()

    for column in columns:
        if column in display_df.columns:
            display_df[column] = display_df[column].map(format_number)

    return display_df


def prepare_business_table(
    df: pd.DataFrame,
    columns: list[str],
    rename_map: dict[str, str] | None = None,
    numeric_columns: list[str] | None = None,
    include_color: bool = True,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    display_df = df.copy()
    requested_columns = list(columns)

    if include_color and (
        "display_color" in requested_columns
        or "color_original" in requested_columns
        or "color_normalized" in requested_columns
    ):
        display_df["display_color"] = display_color_column(display_df)
        requested_columns = [
            "display_color" if column in {"color_original", "color_normalized"} else column
            for column in requested_columns
        ]

    selected_columns = []

    for column in requested_columns:
        if column in display_df.columns and column not in selected_columns:
            selected_columns.append(column)

    display_df = display_df[selected_columns].copy()
    display_df = format_numeric_columns_for_display(display_df, numeric_columns or [])

    labels = COLUMN_LABELS_ES.copy()

    if rename_map:
        labels.update(rename_map)

    return display_df.rename(columns={column: labels.get(column, column) for column in display_df.columns})

