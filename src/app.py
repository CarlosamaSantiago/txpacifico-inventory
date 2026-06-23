from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from export_utils import (
        build_excel_report_bytes,
        build_export_filename,
        build_export_metadata,
        build_filtered_inventory_export,
        dataframe_to_csv_bytes,
        is_export_unfiltered,
    )
except ModuleNotFoundError:
    from src.export_utils import (
        build_excel_report_bytes,
        build_export_filename,
        build_export_metadata,
        build_filtered_inventory_export,
        dataframe_to_csv_bytes,
        is_export_unfiltered,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
POWERBI_DATASET_DIR = PROJECT_ROOT / "reports" / "powerbi" / "dataset"


FILES = {
    "company_summary": PROCESSED_DIR / "company_monthly_inventory_summary.csv",
    "monthly_balance": PROCESSED_DIR / "monthly_inventory_balance.csv",
    "current_inventory": PROCESSED_DIR / "current_inventory_balance.csv",
    "duplicate_lotrols": PROCESSED_DIR / "duplicate_lotrols.csv",
    "negative_alerts": PROCESSED_DIR / "negative_inventory_alerts.csv",
    "stock_movements": PROCESSED_DIR / "stock_movements.csv",
    "container_import_summary": PROCESSED_DIR / "container_import_summary.csv",
    "container_import_header": PROCESSED_DIR / "container_import_header.csv",
    "product_master": PROCESSED_DIR / "product_master_candidate.csv",
    "inventory_exceptions": POWERBI_DATASET_DIR / "fact_inventory_exceptions.csv",
}


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


@st.cache_data
def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def prepare_company_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

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
        "product_keys_with_movement",
        "negative_product_keys",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    return df.sort_values("movement_month")


def prepare_inventory_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

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
        "movement_rows",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    for col in ["reference", "description", "color_normalized", "product_key", "movement_month"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def prepare_movements_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

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
        "source_row",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    text_cols = [
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
        "unit_of_measure",
        "source_file",
        "source_sheet",
        "validation_status",
    ]

    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def prepare_container_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    numeric_cols = [
        "receipt_qty",
        "roll_count",
        "unique_lotrols",
        "duplicate_lotrols_excluded",
        "total_receipt_qty",
        "unique_references",
        "unique_product_keys",
        "unique_colors",
        "duplicate_lotrol_count",
        "duplicate_qty_excluded",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_number(df[col])

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def format_number(value: float) -> str:
    return f"{value:,.2f}"


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def clean_display_value(value) -> str:
    if pd.isna(value):
        return ""

    return str(value).strip()


def first_description(value) -> str:
    text = clean_display_value(value)

    if not text:
        return ""

    return next((part.strip() for part in text.split("|") if part.strip()), text)


def make_product_display_label(row) -> str:
    reference = clean_display_value(row.get("reference", ""))
    description = first_description(row.get("description", ""))
    color = clean_display_value(row.get("color_normalized", ""))

    parts = [part for part in [reference, description, color] if part]

    return " - ".join(parts)


def add_product_display_label(
    df: pd.DataFrame,
    product_selector: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if df.empty or "product_key" not in df.columns:
        return df

    enriched = df.copy()

    if product_selector is not None and not product_selector.empty:
        label_lookup = product_selector[["product_key", "product_display_label"]].drop_duplicates(
            "product_key"
        )
        enriched = enriched.drop(columns=["product_display_label"], errors="ignore").merge(
            label_lookup,
            on="product_key",
            how="left",
        )

    if "product_display_label" not in enriched.columns:
        enriched["product_display_label"] = ""

    missing_label = enriched["product_display_label"].fillna("").astype(str).str.strip().eq("")

    if missing_label.any():
        enriched.loc[missing_label, "product_display_label"] = enriched.loc[missing_label].apply(
            make_product_display_label,
            axis=1,
        )

    return enriched


def build_product_selector_options(data: dict) -> pd.DataFrame:
    frames = []

    product_master = data.get("product_master", pd.DataFrame())

    if not product_master.empty and "product_key" in product_master.columns:
        source = product_master.copy()

        if "descriptions" in source.columns and "description" not in source.columns:
            source["description"] = source["descriptions"].apply(first_description)

        frames.append(source)

    for key in ["monthly_balance", "stock_movements"]:
        source = data.get(key, pd.DataFrame())

        if not source.empty and "product_key" in source.columns:
            frames.append(source.copy())

    if not frames:
        return pd.DataFrame(
            columns=[
                "product_key",
                "reference",
                "description",
                "color_normalized",
                "product_display_label",
            ]
        )

    products = pd.concat(frames, ignore_index=True, sort=False)

    required_cols = ["product_key", "reference", "description", "color_normalized"]

    for col in required_cols:
        if col not in products.columns:
            products[col] = ""

        products[col] = products[col].fillna("").astype(str).str.strip()

    products["description"] = products["description"].apply(first_description)

    products = products[products["product_key"] != ""].copy()
    products = products.sort_values(
        ["product_key", "description"],
        key=lambda series: series.fillna("").astype(str).str.len()
        if series.name == "description"
        else series.fillna("").astype(str),
        ascending=[True, False],
    )
    products = products.drop_duplicates("product_key", keep="first").copy()
    products["product_display_label"] = products.apply(make_product_display_label, axis=1)

    duplicated_label = products["product_display_label"].duplicated(keep=False)

    if duplicated_label.any():
        products.loc[duplicated_label, "product_display_label"] = (
            products.loc[duplicated_label, "product_display_label"]
            + " ("
            + products.loc[duplicated_label, "product_key"]
            + ")"
        )

    return products[
        [
            "product_key",
            "reference",
            "description",
            "color_normalized",
            "product_display_label",
        ]
    ].sort_values(["reference", "description", "color_normalized"])


def load_data():
    company_summary = prepare_company_summary(read_csv(FILES["company_summary"]))
    monthly_balance = prepare_inventory_table(read_csv(FILES["monthly_balance"]))
    current_inventory = prepare_inventory_table(read_csv(FILES["current_inventory"]))
    duplicate_lotrols = read_csv(FILES["duplicate_lotrols"])
    negative_alerts = prepare_inventory_table(read_csv(FILES["negative_alerts"]))
    stock_movements = prepare_movements_table(read_csv(FILES["stock_movements"]))
    container_import_summary = prepare_container_table(read_csv(FILES["container_import_summary"]))
    container_import_header = prepare_container_table(read_csv(FILES["container_import_header"]))
    product_master = read_csv(FILES["product_master"])
    inventory_exceptions = read_csv(FILES["inventory_exceptions"])

    data = {
        "company_summary": company_summary,
        "monthly_balance": monthly_balance,
        "current_inventory": current_inventory,
        "duplicate_lotrols": duplicate_lotrols,
        "negative_alerts": negative_alerts,
        "stock_movements": stock_movements,
        "container_import_summary": container_import_summary,
        "container_import_header": container_import_header,
        "product_master": product_master,
        "inventory_exceptions": inventory_exceptions,
    }

    product_selector = build_product_selector_options(data)

    for key in [
        "monthly_balance",
        "current_inventory",
        "negative_alerts",
        "stock_movements",
        "container_import_summary",
        "container_import_header",
        "duplicate_lotrols",
        "inventory_exceptions",
    ]:
        data[key] = add_product_display_label(data[key], product_selector)

    data["product_selector"] = product_selector

    return data


def render_header():
    st.set_page_config(
        page_title="TXP Inventory Dashboard",
        page_icon="📦",
        layout="wide",
    )

    st.title("📦 TXP Inventory Dashboard")
    st.caption("Inventory tracking from opening stock, import receipts, and sales reports.")


def render_sidebar(data):
    st.sidebar.title("Filters")

    monthly_balance = data["monthly_balance"]
    product_selector = data.get("product_selector", pd.DataFrame())

    if monthly_balance.empty:
        return {}

    months = sorted(monthly_balance["movement_month"].dropna().unique().tolist())
    references = sorted(monthly_balance["reference"].dropna().unique().tolist())
    colors = sorted(monthly_balance["color_normalized"].dropna().unique().tolist())
    product_labels = (
        product_selector["product_display_label"].tolist()
        if not product_selector.empty and "product_display_label" in product_selector.columns
        else []
    )

    selected_month = st.sidebar.selectbox(
        "Inventory month",
        options=months,
        index=len(months) - 1,
    )

    st.sidebar.caption(
        "Puedes buscar por código, nombre de referencia o color. "
        "Ejemplo: 070101, QATAR, PERUANA, PALO DE ROSA."
    )

    selected_product_labels = st.sidebar.multiselect(
        "Buscar referencia / producto / color",
        options=product_labels,
        default=[],
    )

    label_to_key = (
        product_selector.set_index("product_display_label")["product_key"].to_dict()
        if not product_selector.empty
        and {"product_display_label", "product_key"}.issubset(product_selector.columns)
        else {}
    )
    selected_product_keys = [
        label_to_key[label]
        for label in selected_product_labels
        if label in label_to_key
    ]

    quick_search = st.sidebar.text_input(
        "Búsqueda rápida",
        value="",
        placeholder="qatar palo",
    )

    selected_references = st.sidebar.multiselect(
        "Referencia",
        options=references,
        default=[],
    )

    selected_colors = st.sidebar.multiselect(
        "Color",
        options=colors,
        default=[],
    )

    return {
        "selected_month": selected_month,
        "selected_product_labels": selected_product_labels,
        "selected_product_keys": selected_product_keys,
        "quick_search": quick_search,
        "selected_references": selected_references,
        "selected_colors": selected_colors,
    }


def apply_inventory_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    filtered = df.copy()

    selected_product_keys = filters.get("selected_product_keys", [])
    selected_references = filters.get("selected_references", [])
    selected_colors = filters.get("selected_colors", [])
    quick_search = str(filters.get("quick_search", "") or "").strip()

    if selected_product_keys and "product_key" in filtered.columns:
        filtered = filtered[filtered["product_key"].isin(selected_product_keys)]

    if selected_references and "reference" in filtered.columns:
        filtered = filtered[filtered["reference"].isin(selected_references)]

    if selected_colors and "color_normalized" in filtered.columns:
        filtered = filtered[filtered["color_normalized"].isin(selected_colors)]

    if quick_search:
        search_cols = [
            col
            for col in [
                "product_display_label",
                "reference",
                "description",
                "color_normalized",
                "product_key",
            ]
            if col in filtered.columns
        ]

        if search_cols:
            words = [word.upper() for word in quick_search.split() if word.strip()]
            search_text = (
                filtered[search_cols]
                .fillna("")
                .astype(str)
                .agg(" ".join, axis=1)
                .str.upper()
            )

            for word in words:
                filtered = filtered[search_text.str.contains(re.escape(word), na=False)]
                search_text = search_text.loc[filtered.index]

    return filtered


def non_empty_options(df: pd.DataFrame, column: str) -> list[str]:
    if df.empty or column not in df.columns:
        return []

    return sorted(
        value
        for value in df[column].fillna("").astype(str).str.strip().unique().tolist()
        if value
    )


def apply_traceability_filters(
    df: pd.DataFrame,
    reference: str = "ALL",
    color: str = "ALL",
    product_key: str = "ALL",
    movement_group: str = "ALL",
) -> pd.DataFrame:
    filtered = df.copy()

    if reference != "ALL" and "reference" in filtered.columns:
        filtered = filtered[filtered["reference"] == reference]

    if color != "ALL" and "color_normalized" in filtered.columns:
        filtered = filtered[filtered["color_normalized"] == color]

    if product_key != "ALL" and "product_key" in filtered.columns:
        filtered = filtered[filtered["product_key"] == product_key]

    if movement_group != "ALL" and "movement_group" in filtered.columns:
        filtered = filtered[filtered["movement_group"] == movement_group]

    return filtered


def movement_group_label(group: str) -> str:
    return {
        "OPENING": "Inventario inicial",
        "IMPORT": "Importaciones / Contenedores",
        "SALE": "Ventas",
        "ALL": "ALL",
    }.get(group, group)


def render_overview(data, filters):
    company_summary = data["company_summary"]
    monthly_balance = data["monthly_balance"]
    current_inventory = data["current_inventory"]
    duplicate_lotrols = data["duplicate_lotrols"]
    negative_alerts = data["negative_alerts"]

    selected_month = filters.get("selected_month")

    if company_summary.empty or monthly_balance.empty:
        st.error("Processed inventory files were not found. Run the pipeline first.")
        st.code(r".\.venv\Scripts\python.exe src\run_pipeline.py")
        return

    month_inventory = monthly_balance[
        monthly_balance["movement_month"] == selected_month
    ].copy()

    month_inventory = apply_inventory_filters(month_inventory, filters)

    closing_stock = month_inventory["closing_balance"].sum()
    imports_qty = month_inventory["imports_qty"].sum()
    sales_qty = month_inventory["sales_qty"].sum()
    returns_qty = month_inventory["returns_adjustments_qty"].sum()

    negative_count = month_inventory[
        month_inventory["closing_balance"] < -0.0001
    ]["product_key"].nunique()

    duplicate_count = (
        duplicate_lotrols["lotrol"].nunique()
        if not duplicate_lotrols.empty and "lotrol" in duplicate_lotrols.columns
        else 0
    )

    st.subheader(f"Inventory overview — {selected_month}")

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Closing stock", format_number(closing_stock))
    col2.metric("Imports", format_number(imports_qty))
    col3.metric("Sales", format_number(sales_qty))
    col4.metric("Returns / adj.", format_number(returns_qty))
    col5.metric("Negative items", f"{negative_count:,}")
    col6.metric("Duplicate LOTROLs", f"{duplicate_count:,}")

    st.divider()

    filtered_all_months = apply_inventory_filters(monthly_balance, filters)

    if filters.get("selected_product_keys") or filters.get("selected_references") or filters.get("selected_colors") or filters.get("quick_search"):
        company_filtered = (
            filtered_all_months.groupby("movement_month", as_index=False)
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
            )
        )
    else:
        company_filtered = company_summary.copy()

    fig_stock = px.line(
        company_filtered,
        x="movement_month",
        y="closing_balance",
        markers=True,
        title="Company closing stock by month",
    )

    st.plotly_chart(fig_stock, use_container_width=True)

    col_left, col_right = st.columns(2)

    movement_cols = [
        "movement_month",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
    ]

    movement_df = company_filtered[movement_cols].melt(
        id_vars="movement_month",
        var_name="movement",
        value_name="quantity",
    )

    fig_movements = px.bar(
        movement_df,
        x="movement_month",
        y="quantity",
        color="movement",
        barmode="group",
        title="Imports, sales, and returns by month",
    )

    col_left.plotly_chart(fig_movements, use_container_width=True)

    top_inventory = (
        month_inventory.groupby(["reference", "description"], as_index=False)
        .agg(closing_balance=("closing_balance", "sum"))
        .sort_values("closing_balance", ascending=False)
        .head(15)
    )

    fig_top = px.bar(
        top_inventory,
        x="closing_balance",
        y="reference",
        orientation="h",
        hover_data=["description"],
        title="Top 15 references by closing stock",
    )

    col_right.plotly_chart(fig_top, use_container_width=True)

    st.subheader("Current inventory by product/color")

    display_cols = [
        "product_display_label",
        "reference",
        "description",
        "color_normalized",
        "opening_balance",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
        "closing_balance",
    ]

    existing_cols = [col for col in display_cols if col in month_inventory.columns]

    st.dataframe(
        month_inventory[existing_cols].sort_values(
            "closing_balance",
            ascending=False,
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_monthly_balance(data, filters):
    monthly_balance = data["monthly_balance"]

    if monthly_balance.empty:
        st.error("monthly_inventory_balance.csv was not found.")
        return

    filtered = apply_inventory_filters(monthly_balance, filters)

    st.subheader("Month-by-month inventory balance")

    display_cols = [
        "movement_month",
        "product_display_label",
        "reference",
        "description",
        "color_normalized",
        "opening_balance",
        "opening_stock_qty",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
        "net_change",
        "closing_balance",
        "has_negative_closing_balance",
    ]

    existing_cols = [col for col in display_cols if col in filtered.columns]

    st.dataframe(
        filtered[existing_cols].sort_values(
            ["movement_month", "reference", "color_normalized"],
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_duplicates(data, filters):
    duplicate_lotrols = data["duplicate_lotrols"]

    st.subheader("Duplicate LOTROLs")

    duplicate_lotrols = apply_inventory_filters(duplicate_lotrols, filters)

    if duplicate_lotrols.empty:
        st.success("No duplicate LOTROLs found.")
        return

    st.warning(
        f"Found {duplicate_lotrols['lotrol'].nunique():,} duplicated LOTROL values."
    )

    preferred_cols = [
        "lotrol",
        "duplicate_occurrences",
        "duplicate_occurrence_number",
        "should_count_in_inventory",
        "duplicate_qty_excluded",
        "excluded_duplicate_qty",
        "product_display_label",
        "reference",
        "description",
        "color_normalized",
        "qty_in",
        "source_file",
        "source_sheet",
        "source_row",
    ]

    existing_cols = [col for col in preferred_cols if col in duplicate_lotrols.columns]

    st.dataframe(
        duplicate_lotrols[existing_cols],
        use_container_width=True,
        hide_index=True,
    )


def render_negative_alerts(data, filters):
    negative_alerts = data["negative_alerts"]

    st.subheader("Negative inventory alerts")

    negative_alerts = apply_inventory_filters(negative_alerts, filters)

    if negative_alerts.empty:
        st.success("No negative inventory alerts found.")
        return

    st.error(f"Found {len(negative_alerts):,} negative inventory rows.")

    display_cols = [
        "movement_month",
        "product_display_label",
        "reference",
        "description",
        "color_normalized",
        "opening_balance",
        "imports_qty",
        "sales_qty",
        "returns_adjustments_qty",
        "closing_balance",
    ]

    existing_cols = [col for col in display_cols if col in negative_alerts.columns]

    st.dataframe(
        negative_alerts[existing_cols],
        use_container_width=True,
        hide_index=True,
    )


def render_traceability(data, filters):
    monthly_balance = apply_inventory_filters(data["monthly_balance"], filters)
    stock_movements = apply_inventory_filters(data["stock_movements"], filters)
    product_selector = data.get("product_selector", pd.DataFrame())

    st.subheader("Trazabilidad")

    if monthly_balance.empty or stock_movements.empty:
        st.error("Traceability data was not found. Run the pipeline first.")
        return

    st.info(
        "Las ventas disponibles actualmente vienen agregadas por reporte mensual, referencia y color. "
        "Por eso la trazabilidad de ventas llega hasta la fila del reporte de ventas, no hasta factura, "
        "cliente o rollo individual."
    )

    references = ["ALL"] + non_empty_options(monthly_balance, "reference")
    colors = ["ALL"] + non_empty_options(monthly_balance, "color_normalized")
    available_product_keys = set(non_empty_options(monthly_balance, "product_key"))
    available_products = (
        product_selector[product_selector["product_key"].isin(available_product_keys)].copy()
        if not product_selector.empty and "product_key" in product_selector.columns
        else pd.DataFrame()
    )
    product_labels = ["ALL"] + (
        available_products["product_display_label"].tolist()
        if not available_products.empty and "product_display_label" in available_products.columns
        else non_empty_options(monthly_balance, "product_display_label")
    )
    label_to_key = (
        available_products.set_index("product_display_label")["product_key"].to_dict()
        if not available_products.empty
        and {"product_display_label", "product_key"}.issubset(available_products.columns)
        else {}
    )
    movement_groups = ["ALL", "OPENING", "IMPORT", "SALE"]

    col1, col2, col3, col4 = st.columns(4)

    selected_reference = col1.selectbox("Referencia", options=references, key="trace_reference")
    selected_color = col2.selectbox("Color", options=colors, key="trace_color")
    selected_product_label = col3.selectbox(
        "Producto seleccionado",
        options=product_labels,
        key="trace_product_label",
    )
    selected_product_key = (
        "ALL"
        if selected_product_label == "ALL"
        else label_to_key.get(selected_product_label, "ALL")
    )
    selected_movement_group = col4.selectbox(
        "Movement group",
        options=movement_groups,
        format_func=movement_group_label,
        key="trace_movement_group",
    )

    filtered_monthly = apply_traceability_filters(
        monthly_balance,
        reference=selected_reference,
        color=selected_color,
        product_key=selected_product_key,
    )

    if filtered_monthly.empty:
        st.warning("No monthly balance rows match the selected filters.")
        return

    monthly_matrix = (
        filtered_monthly.groupby("movement_month", as_index=False)
        .agg(
            opening_balance=("opening_balance", "sum"),
            imports_qty=("imports_qty", "sum"),
            sales_qty=("sales_qty", "sum"),
            returns_adjustments_qty=("returns_adjustments_qty", "sum"),
            net_change=("net_change", "sum"),
            closing_balance=("closing_balance", "sum"),
        )
        .sort_values("movement_month")
    )

    display_matrix = monthly_matrix.rename(
        columns={
            "movement_month": "movement_month",
            "opening_balance": "Saldo inicial",
            "imports_qty": "Importaciones / Contenedores",
            "sales_qty": "Ventas",
            "returns_adjustments_qty": "Devoluciones / Ajustes",
            "net_change": "net_change",
            "closing_balance": "Saldo final",
        }
    )

    st.dataframe(display_matrix, use_container_width=True, hide_index=True)

    fig = px.line(
        monthly_matrix,
        x="movement_month",
        y="closing_balance",
        markers=True,
        title="Saldo final por mes",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "Download filtered monthly balance CSV",
        data=to_csv_bytes(monthly_matrix),
        file_name="filtered_monthly_traceability.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Movement Detail / Supporting Records")

    month_options = ["ALL"] + monthly_matrix["movement_month"].tolist()
    detail_month = st.selectbox("Selected month", options=month_options, key="trace_detail_month")
    detail_group = st.selectbox(
        "Selected movement group",
        options=movement_groups,
        format_func=movement_group_label,
        key="trace_detail_group",
    )

    effective_group = selected_movement_group if selected_movement_group != "ALL" else detail_group
    detail = apply_traceability_filters(
        stock_movements,
        reference=selected_reference,
        color=selected_color,
        product_key=selected_product_key,
        movement_group=effective_group,
    )

    if detail_month != "ALL" and "movement_month" in detail.columns:
        detail = detail[detail["movement_month"] == detail_month]

    if detail.empty:
        st.warning("No supporting movement records match the selected detail filters.")
        return

    base_cols = [
        "movement_date",
        "movement_month",
        "movement_group",
        "movement_type",
        "product_display_label",
        "reference",
        "description",
        "color_normalized",
        "qty_in",
        "qty_out",
        "net_qty",
        "validation_status",
    ]

    import_cols = [
        "ibum_id",
        "container_key",
        "source_file",
        "lot",
        "roll",
        "lotrol",
        "source_sheet",
        "source_row",
    ]
    sale_cols = [
        "source_file",
        "source_sheet",
        "source_row",
        "movement_subtype",
        "subtotal",
        "period_start",
        "period_end",
    ]
    opening_cols = [
        "location",
        "lotrol",
        "source_file",
        "source_sheet",
        "source_row",
        "traceability_level",
    ]

    if effective_group == "IMPORT":
        preferred_cols = base_cols[:2] + import_cols[:3] + base_cols[4:8] + import_cols[3:6] + [
            "qty_in",
            "validation_status",
            "source_sheet",
            "source_row",
        ]
    elif effective_group == "SALE":
        preferred_cols = base_cols + sale_cols
    elif effective_group == "OPENING":
        preferred_cols = base_cols + opening_cols
    else:
        preferred_cols = base_cols + [
            "ibum_id",
            "container_key",
            "lot",
            "roll",
            "lotrol",
            "location",
            "source_file",
            "source_sheet",
            "source_row",
            "traceability_level",
        ]

    existing_cols = [col for col in preferred_cols if col in detail.columns]

    sort_cols = [
        col
        for col in ["movement_month", "movement_group", "source_file", "source_row"]
        if col in detail.columns
    ]
    display_detail = detail[existing_cols].copy()
    display_sort_cols = [col for col in sort_cols if col in display_detail.columns]

    if display_sort_cols:
        display_detail = display_detail.sort_values(display_sort_cols)

    st.dataframe(
        display_detail,
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "Download supporting movement records CSV",
        data=to_csv_bytes(detail),
        file_name="filtered_supporting_movements.csv",
        mime="text/csv",
    )


def render_containers(data, filters):
    container_header = data["container_import_header"]
    container_summary = apply_inventory_filters(data["container_import_summary"], filters)
    stock_movements = apply_inventory_filters(data["stock_movements"], filters)
    duplicate_lotrols = apply_inventory_filters(data["duplicate_lotrols"], filters)

    st.subheader("Containers / IBUM")

    if container_header.empty:
        st.error("container_import_header.csv was not found. Run the pipeline first.")
        return

    if not container_summary.empty and "container_key" in container_summary.columns:
        visible_containers = set(container_summary["container_key"].dropna().astype(str))
        container_header = container_header[
            container_header["container_key"].fillna("").astype(str).isin(visible_containers)
        ].copy()

    if container_header.empty:
        st.warning("No containers match the selected product filters.")
        return

    st.dataframe(
        container_header.sort_values(["movement_month", "container_key"]),
        use_container_width=True,
        hide_index=True,
    )

    container_options = container_header["container_key"].dropna().astype(str).tolist()
    selected_container = st.selectbox("IBUM / container_key", options=container_options)

    selected_header = container_header[container_header["container_key"] == selected_container]

    if selected_header.empty:
        return

    row = selected_header.iloc[0]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("IBUM", row.get("ibum_id", "") or "MISSING")
    col2.metric("Total kg imported", format_number(float(row.get("total_receipt_qty", 0) or 0)))
    col3.metric("References", f"{int(float(row.get('unique_references', 0) or 0)):,}")
    col4.metric("Colors", f"{int(float(row.get('unique_colors', 0) or 0)):,}")
    col5.metric("Rolls", f"{int(float(row.get('unique_lotrols', 0) or 0)):,}")

    selected_summary = container_summary[
        container_summary["container_key"] == selected_container
    ].copy() if not container_summary.empty else pd.DataFrame()

    st.subheader("Summary by reference/color")
    if selected_summary.empty:
        st.warning("No container summary rows found for the selected container.")
    else:
        summary_cols = [
            "ibum_id",
            "source_file",
            "movement_date",
            "movement_month",
            "product_display_label",
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
        existing_cols = [col for col in summary_cols if col in selected_summary.columns]
        st.dataframe(selected_summary[existing_cols], use_container_width=True, hide_index=True)

    import_detail = stock_movements[
        stock_movements["container_key"] == selected_container
    ].copy() if not stock_movements.empty and "container_key" in stock_movements.columns else pd.DataFrame()

    st.subheader("Roll-level records")
    if import_detail.empty:
        st.warning("No roll-level import records found for the selected container.")
    else:
        detail_cols = [
            "movement_date",
            "movement_month",
            "ibum_id",
            "source_file",
            "product_display_label",
            "reference",
            "description",
            "color_normalized",
            "lot",
            "roll",
            "lotrol",
            "qty_in",
            "validation_status",
            "source_sheet",
            "source_row",
        ]
        existing_cols = [col for col in detail_cols if col in import_detail.columns]
        st.dataframe(
            import_detail[existing_cols].sort_values(["reference", "color_normalized", "lotrol"]),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Duplicated LOTROLs")
    duplicate_detail = pd.DataFrame()

    if not duplicate_lotrols.empty and "container_key" in duplicate_lotrols.columns:
        duplicate_detail = duplicate_lotrols[
            duplicate_lotrols["container_key"].fillna("").astype(str) == selected_container
        ].copy()

    if duplicate_detail.empty:
        st.success("No duplicated LOTROLs found for this container.")
    else:
        duplicate_cols = [
            "ibum_id",
            "container_key",
            "lotrol",
            "duplicate_occurrences",
            "duplicate_occurrence_number",
            "should_count_in_inventory",
            "duplicate_qty_excluded",
            "reference",
            "description",
            "color_normalized",
            "qty_in",
            "source_file",
            "source_sheet",
            "source_row",
        ]
        existing_cols = [col for col in duplicate_cols if col in duplicate_detail.columns]
        st.dataframe(duplicate_detail[existing_cols], use_container_width=True, hide_index=True)

    if not import_detail.empty:
        st.download_button(
            "Download selected container detail CSV",
            data=to_csv_bytes(import_detail),
            file_name=f"{selected_container.replace(':', '_')}_container_detail.csv",
            mime="text/csv",
        )


def render_export_report(data, filters):
    st.subheader("Exportar reporte")
    st.caption(
        "Descarga el balance mensual, movimientos soporte, importaciones, ventas, "
        "contenedores IBUM y alertas según los filtros activos."
    )

    st.info(
        "Nota: Las ventas disponibles actualmente vienen agregadas por reporte mensual, "
        "referencia y color. Por eso la trazabilidad de ventas llega hasta la fila del "
        "reporte de ventas, no hasta factura, cliente o rollo individual."
    )

    filtered_monthly = apply_inventory_filters(data.get("monthly_balance", pd.DataFrame()), filters)
    available_months = (
        sorted(filtered_monthly["movement_month"].dropna().astype(str).unique().tolist())
        if not filtered_monthly.empty and "movement_month" in filtered_monthly.columns
        else []
    )

    selected_export_months = st.multiselect(
        "Meses a exportar",
        options=available_months,
        default=available_months,
    )

    if is_export_unfiltered(filters):
        st.warning("Estás a punto de exportar toda la información disponible.")

    if available_months and not selected_export_months:
        st.warning("Selecciona al menos un mes para incluir datos en el reporte.")

    if st.button("Preparar descargas", type="primary"):
        st.session_state["export_report_ready"] = True

    if not st.session_state.get("export_report_ready", False):
        st.caption(
            "Presiona Preparar descargas para generar el Excel y los CSV con los filtros actuales."
        )
        return

    export_tables = build_filtered_inventory_export(
        data=data,
        filters=filters,
        filter_func=apply_inventory_filters,
        selected_export_months=selected_export_months,
    )
    metadata = build_export_metadata(
        export_tables=export_tables,
        filters=filters,
        selected_export_months=selected_export_months,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Productos", f"{int(metadata.get('products_included', 0)):,}")
    col2.metric("Movimientos soporte", f"{int(metadata.get('movement_support_rows', 0)):,}")
    col3.metric("Importaciones", f"{int(metadata.get('import_rows', 0)):,}")
    col4.metric("Ventas", f"{int(metadata.get('sales_rows', 0)):,}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Total importaciones", format_number(float(metadata.get("total_imports", 0) or 0)))
    col6.metric("Total ventas", format_number(float(metadata.get("total_sales", 0) or 0)))
    col7.metric("Saldo final", format_number(float(metadata.get("latest_closing_stock", 0) or 0)))
    col8.metric("Alertas / Excepciones", f"{int(metadata.get('exception_rows', 0)):,}")

    excel_file_name = build_export_filename(filters, suffix="xlsx")
    csv_base_name = build_export_filename(filters, suffix="csv").replace(".csv", "")

    try:
        excel_bytes = build_excel_report_bytes(export_tables, metadata)
        st.download_button(
            "Descargar Excel",
            data=excel_bytes,
            file_name=excel_file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.error(f"No se pudo generar el Excel: {exc}")

    st.divider()
    st.subheader("Descargar CSV")

    csv_downloads = [
        ("Balance mensual filtrado", "Balance mensual", "balance_mensual"),
        ("Movimientos soporte", "Movimientos soporte", "movimientos_soporte"),
        ("Importaciones / Contenedores", "Importaciones", "importaciones"),
        ("Ventas", "Ventas", "ventas"),
        ("Contenedores IBUM", "Contenedores IBUM", "contenedores_ibum"),
        ("Alertas / Excepciones", "Excepciones", "excepciones"),
    ]

    for label, table_key, file_token in csv_downloads:
        table = export_tables.get(table_key, pd.DataFrame())

        if table.empty:
            st.caption(f"{label}: sin filas para los filtros actuales.")
            continue

        st.download_button(
            f"Descargar CSV - {label}",
            data=dataframe_to_csv_bytes(table),
            file_name=f"{csv_base_name}_{file_token}.csv",
            mime="text/csv",
            key=f"download_{file_token}",
        )

    st.divider()
    st.subheader("Vista previa")

    preview_table = export_tables.get("Balance mensual", pd.DataFrame())

    if preview_table.empty:
        st.warning("No hay balance mensual para los filtros seleccionados.")
    else:
        st.dataframe(preview_table.head(100), use_container_width=True, hide_index=True)


def main():
    render_header()

    data = load_data()
    filters = render_sidebar(data)

    tabs = st.tabs(
        [
            "Overview",
            "Monthly Balance",
            "Trazabilidad",
            "Containers / IBUM",
            "Exportar reporte",
            "Duplicate LOTROLs",
            "Negative Inventory",
        ]
    )

    with tabs[0]:
        render_overview(data, filters)

    with tabs[1]:
        render_monthly_balance(data, filters)

    with tabs[2]:
        render_traceability(data, filters)

    with tabs[3]:
        render_containers(data, filters)

    with tabs[4]:
        render_export_report(data, filters)

    with tabs[5]:
        render_duplicates(data, filters)

    with tabs[6]:
        render_negative_alerts(data, filters)


if __name__ == "__main__":
    main()
