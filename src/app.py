from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


FILES = {
    "company_summary": PROCESSED_DIR / "company_monthly_inventory_summary.csv",
    "monthly_balance": PROCESSED_DIR / "monthly_inventory_balance.csv",
    "current_inventory": PROCESSED_DIR / "current_inventory_balance.csv",
    "duplicate_lotrols": PROCESSED_DIR / "duplicate_lotrols.csv",
    "negative_alerts": PROCESSED_DIR / "negative_inventory_alerts.csv",
    "stock_movements": PROCESSED_DIR / "stock_movements.csv",
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


def format_number(value: float) -> str:
    return f"{value:,.2f}"


def load_data():
    company_summary = prepare_company_summary(read_csv(FILES["company_summary"]))
    monthly_balance = prepare_inventory_table(read_csv(FILES["monthly_balance"]))
    current_inventory = prepare_inventory_table(read_csv(FILES["current_inventory"]))
    duplicate_lotrols = read_csv(FILES["duplicate_lotrols"])
    negative_alerts = prepare_inventory_table(read_csv(FILES["negative_alerts"]))
    stock_movements = read_csv(FILES["stock_movements"])

    return {
        "company_summary": company_summary,
        "monthly_balance": monthly_balance,
        "current_inventory": current_inventory,
        "duplicate_lotrols": duplicate_lotrols,
        "negative_alerts": negative_alerts,
        "stock_movements": stock_movements,
    }


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

    if monthly_balance.empty:
        return {}

    months = sorted(monthly_balance["movement_month"].dropna().unique().tolist())
    references = sorted(monthly_balance["reference"].dropna().unique().tolist())
    colors = sorted(monthly_balance["color_normalized"].dropna().unique().tolist())

    selected_month = st.sidebar.selectbox(
        "Inventory month",
        options=months,
        index=len(months) - 1,
    )

    selected_references = st.sidebar.multiselect(
        "Reference",
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
        "selected_references": selected_references,
        "selected_colors": selected_colors,
    }


def apply_inventory_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    filtered = df.copy()

    selected_references = filters.get("selected_references", [])
    selected_colors = filters.get("selected_colors", [])

    if selected_references:
        filtered = filtered[filtered["reference"].isin(selected_references)]

    if selected_colors:
        filtered = filtered[filtered["color_normalized"].isin(selected_colors)]

    return filtered


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


def render_duplicates(data):
    duplicate_lotrols = data["duplicate_lotrols"]

    st.subheader("Duplicate LOTROLs")

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


def render_negative_alerts(data):
    negative_alerts = data["negative_alerts"]

    st.subheader("Negative inventory alerts")

    if negative_alerts.empty:
        st.success("No negative inventory alerts found.")
        return

    st.error(f"Found {len(negative_alerts):,} negative inventory rows.")

    display_cols = [
        "movement_month",
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


def main():
    render_header()

    data = load_data()
    filters = render_sidebar(data)

    tabs = st.tabs(
        [
            "Overview",
            "Monthly Balance",
            "Duplicate LOTROLs",
            "Negative Inventory",
        ]
    )

    with tabs[0]:
        render_overview(data, filters)

    with tabs[1]:
        render_monthly_balance(data, filters)

    with tabs[2]:
        render_duplicates(data)

    with tabs[3]:
        render_negative_alerts(data)


if __name__ == "__main__":
    main()