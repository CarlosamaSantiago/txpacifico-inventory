# TXP Power BI Dataset

Use these CSV files as the Power BI semantic model.

## Recommended relationships

- dim_product_variant[product_key] 1 -> many fact_stock_movements[product_key]
- dim_product_variant[product_key] 1 -> many fact_monthly_inventory_balance[product_key]
- dim_month[movement_month] 1 -> many fact_stock_movements[movement_month]
- dim_month[movement_month] 1 -> many fact_monthly_inventory_balance[movement_month]
- dim_month[movement_month] 1 -> many fact_company_monthly_summary[movement_month]
- dim_container[container_key] 1 -> many fact_stock_movements[container_key]
- dim_container[container_key] 1 -> many fact_container_import_summary[container_key]
- dim_product_variant[product_key] 1 -> many fact_container_import_summary[product_key]

## Main fact tables

- fact_stock_movements: detailed inventory ledger.
- fact_monthly_inventory_balance: monthly stock balance by product/color.
- fact_company_monthly_summary: company-level monthly stock balance.
- fact_duplicate_lotrols: duplicated receipt roll alerts.
- fact_container_import_summary: container receipts by reference/color.
- fact_inventory_exceptions: combined data quality alerts.

## Core measures to create in Power BI

Current Stock = SUM(fact_monthly_inventory_balance[closing_balance])

Total Imports = SUM(fact_monthly_inventory_balance[imports_qty])

Total Sales = SUM(fact_monthly_inventory_balance[sales_qty])

Total Returns / Adjustments = SUM(fact_monthly_inventory_balance[returns_adjustments_qty])

Net Change = SUM(fact_monthly_inventory_balance[net_change])

Negative Stock Items = COUNTROWS(FILTER(fact_monthly_inventory_balance, fact_monthly_inventory_balance[has_negative_closing_balance] = TRUE()))
