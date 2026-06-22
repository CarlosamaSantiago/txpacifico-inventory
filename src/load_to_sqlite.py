from pathlib import Path
import sqlite3

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = DB_DIR / "txp_inventory.db"


TABLES = {
    "stock_movements": PROCESSED_DIR / "stock_movements.csv",
    "monthly_inventory_balance": PROCESSED_DIR / "monthly_inventory_balance.csv",
    "current_inventory_balance": PROCESSED_DIR / "current_inventory_balance.csv",
    "company_monthly_inventory_summary": PROCESSED_DIR / "company_monthly_inventory_summary.csv",
    "negative_inventory_alerts": PROCESSED_DIR / "negative_inventory_alerts.csv",
    "duplicate_lotrols": PROCESSED_DIR / "duplicate_lotrols.csv",
    "product_master_candidate": PROCESSED_DIR / "product_master_candidate.csv",
    "stock_movements_summary_by_type": PROCESSED_DIR / "stock_movements_summary_by_type.csv",
    "stock_movements_summary_by_month": PROCESSED_DIR / "stock_movements_summary_by_month.csv",
    "opening_stock_quality_checks": PROCESSED_DIR / "opening_stock_quality_checks.csv",
    "sales_quality_checks": PROCESSED_DIR / "sales_quality_checks.csv",
    "receipts_quality_checks": PROCESSED_DIR / "receipts_quality_checks.csv",
    "stock_movements_quality_checks": PROCESSED_DIR / "stock_movements_quality_checks.csv",
}


def read_csv_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"WARNING: Missing file, skipping: {path}")
        return pd.DataFrame()

    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def create_indexes(connection: sqlite3.Connection) -> None:
    indexes = [
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_month_product
        ON stock_movements (movement_month, product_key);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_type
        ON stock_movements (movement_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_lotrol
        ON stock_movements (lotrol);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_monthly_balance_month_product
        ON monthly_inventory_balance (movement_month, product_key);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_current_inventory_product
        ON current_inventory_balance (product_key);
        """,
    ]

    for index_sql in indexes:
        connection.execute(index_sql)

    connection.commit()


def create_pipeline_metadata(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    connection.execute(
        """
        INSERT OR REPLACE INTO pipeline_metadata (key, value)
        VALUES ('database_created_by', 'TXP inventory pipeline');
        """
    )

    connection.execute(
        """
        INSERT OR REPLACE INTO pipeline_metadata (key, value)
        VALUES ('database_type', 'SQLite local MVP');
        """
    )

    connection.commit()


def main() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Creating SQLite database: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as connection:
        for table_name, csv_path in TABLES.items():
            print(f"Loading table: {table_name}")

            df = read_csv_safely(csv_path)

            if df.empty:
                print(f"  Skipped empty/missing table: {table_name}")
                continue

            df.to_sql(
                table_name,
                connection,
                if_exists="replace",
                index=False,
            )

            print(f"  Rows loaded: {len(df):,}")

        create_indexes(connection)
        create_pipeline_metadata(connection)

    print("Done.")
    print(f"SQLite database created at: {DB_PATH}")


if __name__ == "__main__":
    main()