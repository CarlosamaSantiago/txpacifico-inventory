from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from typing import Callable

import pandas as pd


MONTHLY_BALANCE_COLUMNS = [
    "movement_month",
    "product_display_label",
    "reference",
    "description",
    "color_normalized",
    "product_key",
    "opening_balance",
    "opening_stock_qty",
    "imports_qty",
    "sales_qty",
    "returns_adjustments_qty",
    "net_change",
    "closing_balance",
    "has_negative_closing_balance",
]

MOVEMENT_SUPPORT_COLUMNS = [
    "movement_id",
    "movement_date",
    "movement_month",
    "movement_group",
    "movement_type",
    "movement_subtype",
    "traceability_level",
    "product_display_label",
    "reference",
    "description",
    "color_normalized",
    "product_key",
    "ibum_id",
    "container_key",
    "lot",
    "roll",
    "lotrol",
    "qty_in",
    "qty_out",
    "net_qty",
    "source_file",
    "source_sheet",
    "source_row",
    "validation_status",
]

IMPORT_COLUMNS = [
    "ibum_id",
    "container_key",
    "source_files",
    "movement_months",
    "source_file",
    "movement_date",
    "movement_month",
    "product_display_label",
    "reference",
    "description",
    "color_normalized",
    "product_key",
    "receipt_qty",
    "roll_count",
    "unique_lotrols",
    "duplicate_lotrols_excluded",
    "qty_in",
    "lotrol",
    "validation_status",
    "source_sheet",
    "source_row",
]

CONTAINER_COLUMNS = [
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

SALES_COLUMNS = [
    "movement_date",
    "movement_month",
    "movement_type",
    "movement_subtype",
    "traceability_level",
    "product_display_label",
    "reference",
    "description",
    "color_normalized",
    "product_key",
    "qty_out",
    "qty_in",
    "net_qty",
    "source_file",
    "source_sheet",
    "source_row",
    "validation_status",
]

EXCEPTION_COLUMNS = [
    "issue_type",
    "issue_detail",
    "movement_month",
    "product_display_label",
    "reference",
    "description",
    "color_normalized",
    "product_key",
    "closing_balance",
    "qty_in",
    "qty_out",
    "net_qty",
    "source_file",
    "source_sheet",
    "source_row",
]


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def select_existing_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    existing_columns = [column for column in columns if column in df.columns]
    remaining_columns = [column for column in df.columns if column not in existing_columns]

    return df[existing_columns + remaining_columns].copy()


def safe_filename(text: str) -> str:
    cleaned = str(text or "").strip().upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")

    return cleaned[:120] or "FILTRADO"


def build_export_filename(filters: dict, suffix: str = "xlsx") -> str:
    labels = filters.get("selected_product_labels") or []
    descriptions = filters.get("selected_descriptions") or []
    references = filters.get("selected_references") or []
    colors = filters.get("selected_colors") or []

    if len(labels) == 1:
        token = safe_filename(labels[0])
    elif len(descriptions) == 1 and not labels and not references and not colors:
        token = safe_filename(descriptions[0])
    elif len(references) == 1 and len(colors) <= 1 and not labels and not descriptions:
        token_parts = references + colors
        token = safe_filename("_".join(token_parts))
    elif len(colors) == 1 and not labels and not descriptions and not references:
        token = safe_filename(colors[0])
    else:
        token = "FILTRADO"

    return f"TXP_reporte_inventario_{token}.{suffix}"


def is_export_unfiltered(filters: dict) -> bool:
    return not any(
        [
            filters.get("selected_product_keys"),
            filters.get("selected_descriptions"),
            filters.get("selected_references"),
            filters.get("selected_colors"),
            str(filters.get("quick_search", "") or "").strip(),
        ]
    )


def _filter_table(
    data: dict,
    table_name: str,
    filters: dict,
    filter_func: Callable[[pd.DataFrame, dict], pd.DataFrame],
) -> pd.DataFrame:
    df = data.get(table_name, pd.DataFrame())

    if df.empty:
        return pd.DataFrame()

    return filter_func(df, filters)


def _filter_by_months(df: pd.DataFrame, months: list[str] | None) -> pd.DataFrame:
    if df.empty or not months or "movement_month" not in df.columns:
        return df

    return df[df["movement_month"].isin(months)].copy()


def build_filtered_inventory_export(
    data: dict,
    filters: dict,
    filter_func: Callable[[pd.DataFrame, dict], pd.DataFrame],
    selected_export_months: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    monthly_balance = _filter_by_months(
        _filter_table(data, "monthly_balance", filters, filter_func),
        selected_export_months,
    )
    movements = _filter_by_months(
        _filter_table(data, "stock_movements", filters, filter_func),
        selected_export_months,
    )
    container_summary = _filter_by_months(
        _filter_table(data, "container_import_summary", filters, filter_func),
        selected_export_months,
    )
    negative_alerts = _filter_by_months(
        _filter_table(data, "negative_alerts", filters, filter_func),
        selected_export_months,
    )
    duplicate_lotrols = _filter_by_months(
        _filter_table(data, "duplicate_lotrols", filters, filter_func),
        selected_export_months,
    )
    inventory_exceptions = _filter_by_months(
        _filter_table(data, "inventory_exceptions", filters, filter_func),
        selected_export_months,
    )

    imports_from_movements = pd.DataFrame()
    sales = pd.DataFrame()

    if not movements.empty and "movement_group" in movements.columns:
        imports_from_movements = movements[movements["movement_group"].eq("IMPORT")].copy()
        sales = movements[movements["movement_group"].eq("SALE")].copy()
    elif not movements.empty and "movement_type" in movements.columns:
        imports_from_movements = movements[movements["movement_type"].eq("CONTAINER_RECEIPT")].copy()
        sales = movements[
            movements["movement_type"].isin(["SALE", "SALES_RETURN_OR_ADJUSTMENT"])
        ].copy()

    imports = container_summary.copy()

    if imports.empty:
        imports = imports_from_movements.copy()

    container_header = data.get("container_import_header", pd.DataFrame()).copy()

    if not container_header.empty and not imports.empty and "container_key" in imports.columns:
        visible_keys = set(imports["container_key"].fillna("").astype(str))

        if "container_key" in container_header.columns:
            container_header = container_header[
                container_header["container_key"].fillna("").astype(str).isin(visible_keys)
            ].copy()
    elif not container_header.empty and not movements.empty and "container_key" in movements.columns:
        visible_keys = set(movements["container_key"].fillna("").astype(str))
        container_header = container_header[
            container_header["container_key"].fillna("").astype(str).isin(visible_keys)
        ].copy()

    exception_frames = [
        frame
        for frame in [inventory_exceptions, negative_alerts, duplicate_lotrols]
        if not frame.empty
    ]
    exceptions = (
        pd.concat(exception_frames, ignore_index=True, sort=False)
        if exception_frames
        else pd.DataFrame()
    )

    return {
        "Balance mensual": select_existing_columns(monthly_balance, MONTHLY_BALANCE_COLUMNS),
        "Movimientos soporte": select_existing_columns(movements, MOVEMENT_SUPPORT_COLUMNS),
        "Importaciones": select_existing_columns(imports, IMPORT_COLUMNS),
        "Ventas": select_existing_columns(sales, SALES_COLUMNS),
        "Contenedores IBUM": select_existing_columns(container_header, CONTAINER_COLUMNS),
        "Excepciones": select_existing_columns(exceptions, EXCEPTION_COLUMNS),
    }


def _sum_column(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0

    return pd.to_numeric(df[column], errors="coerce").fillna(0.0).sum()


def build_export_metadata(
    export_tables: dict[str, pd.DataFrame],
    filters: dict,
    selected_export_months: list[str] | None = None,
) -> dict[str, object]:
    monthly = export_tables.get("Balance mensual", pd.DataFrame())
    movements = export_tables.get("Movimientos soporte", pd.DataFrame())
    imports = export_tables.get("Importaciones", pd.DataFrame())
    sales = export_tables.get("Ventas", pd.DataFrame())
    exceptions = export_tables.get("Excepciones", pd.DataFrame())

    latest_closing_stock = 0.0

    if not monthly.empty and "movement_month" in monthly.columns and "closing_balance" in monthly.columns:
        latest_month = monthly["movement_month"].max()
        latest_closing_stock = _sum_column(
            monthly[monthly["movement_month"].eq(latest_month)],
            "closing_balance",
        )

    if not monthly.empty and "movement_month" in monthly.columns:
        first_month = monthly["movement_month"].min()
        latest_month = monthly["movement_month"].max()
    else:
        first_month = ""
        latest_month = ""

    product_count = (
        monthly["product_key"].nunique()
        if not monthly.empty and "product_key" in monthly.columns
        else 0
    )

    negative_alerts = 0

    if not monthly.empty and "has_negative_closing_balance" in monthly.columns:
        negative_alerts = int(
            monthly["has_negative_closing_balance"].astype(str).str.upper().isin(["TRUE", "1", "YES"]).sum()
        )

    return {
        "generated_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "selected_product_labels": " | ".join(filters.get("selected_product_labels") or []),
        "selected_descriptions": " | ".join(filters.get("selected_descriptions") or []),
        "selected_references": " | ".join(filters.get("selected_references") or []),
        "selected_colors": " | ".join(filters.get("selected_colors") or []),
        "quick_search": filters.get("quick_search", ""),
        "selected_export_months": " | ".join(selected_export_months or []),
        "products_included": product_count,
        "first_month": first_month,
        "latest_month": latest_month,
        "total_opening_balance": _sum_column(monthly, "opening_balance"),
        "total_imports": _sum_column(monthly, "imports_qty"),
        "total_sales": _sum_column(monthly, "sales_qty"),
        "total_returns_adjustments": _sum_column(monthly, "returns_adjustments_qty"),
        "latest_closing_stock": latest_closing_stock,
        "negative_stock_alerts": negative_alerts,
        "movement_support_rows": len(movements),
        "import_rows": len(imports),
        "sales_rows": len(sales),
        "exception_rows": len(exceptions),
    }


def build_summary_dataframe(metadata: dict[str, object]) -> pd.DataFrame:
    labels = {
        "generated_timestamp": "Fecha de generación",
        "selected_product_labels": "Productos seleccionados",
        "selected_references": "Referencias seleccionadas",
        "selected_colors": "Colores seleccionados",
        "quick_search": "Búsqueda rápida",
        "selected_export_months": "Meses exportados",
        "products_included": "Número de productos incluidos",
        "first_month": "Primer mes",
        "latest_month": "Último mes",
        "total_opening_balance": "Saldo inicial total en rango",
        "total_imports": "Total importaciones",
        "total_sales": "Total ventas",
        "total_returns_adjustments": "Total devoluciones / ajustes",
        "latest_closing_stock": "Saldo final último mes",
        "negative_stock_alerts": "Alertas de saldo negativo",
        "movement_support_rows": "Filas de movimientos soporte",
        "import_rows": "Filas de importaciones",
        "sales_rows": "Filas de ventas",
        "exception_rows": "Filas de alertas / excepciones",
    }

    return pd.DataFrame(
        [
            {"Métrica": labels.get(key, key), "Valor": value}
            for key, value in metadata.items()
        ]
    )


def build_excel_report_bytes(
    export_tables: dict[str, pd.DataFrame],
    metadata: dict[str, object],
) -> bytes:
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary = build_summary_dataframe(metadata)
        summary.to_excel(writer, sheet_name="Resumen", index=False)

        for sheet_name, df in export_tables.items():
            safe_sheet_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_sheet_name, index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"

            for column_cells in worksheet.columns:
                max_length = max(
                    len(str(cell.value)) if cell.value is not None else 0
                    for cell in column_cells
                )
                adjusted_width = min(max(max_length + 2, 10), 60)
                worksheet.column_dimensions[column_cells[0].column_letter].width = adjusted_width

    return output.getvalue()
