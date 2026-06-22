from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


PIPELINE_STEPS = [
    {
        "name": "Extract ZIP",
        "script": SRC_DIR / "extract_zip.py",
    },
    {
        "name": "Parse opening stock",
        "script": SRC_DIR / "parse_opening_stock.py",
    },
    {
        "name": "Parse sales",
        "script": SRC_DIR / "parse_sales.py",
    },
    {
        "name": "Parse receipts / containers",
        "script": SRC_DIR / "parse_receipts.py",
    },
    {
        "name": "Build stock movement ledger",
        "script": SRC_DIR / "build_ledger.py",
    },
    {
        "name": "Build monthly inventory balance",
        "script": SRC_DIR / "build_monthly_balance.py",
    },
    {
        "name": "Load processed data to SQLite",
        "script": SRC_DIR / "load_to_sqlite.py",
    },
    {
        "name": "Create Power BI exports",
        "script": SRC_DIR / "create_powerbi_exports.py",
    },
    {
        "name": "Validate pipeline outputs",
        "script": SRC_DIR / "validate_pipeline_outputs.py",
    },
]


def run_step(step_number: int, total_steps: int, name: str, script: Path) -> None:
    if not script.exists():
        raise FileNotFoundError(f"Missing script: {script}")

    print("=" * 90)
    print(f"STEP {step_number}/{total_steps}: {name}")
    print(f"Running: {script}")
    print("=" * 90)

    start_time = time.time()

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=PROJECT_ROOT,
        text=True,
    )

    elapsed_seconds = time.time() - start_time

    if result.returncode != 0:
        raise RuntimeError(
            f"Pipeline failed at step {step_number}: {name}. "
            f"Script: {script.name}"
        )

    print(f"Finished step {step_number}/{total_steps}: {name}")
    print(f"Elapsed: {elapsed_seconds:.2f} seconds")
    print()


def main() -> None:
    print("TXP Inventory Pipeline")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python executable: {sys.executable}")
    print()

    total_steps = len(PIPELINE_STEPS)

    start_time = time.time()

    for index, step in enumerate(PIPELINE_STEPS, start=1):
        run_step(
            step_number=index,
            total_steps=total_steps,
            name=step["name"],
            script=step["script"],
        )

    elapsed_seconds = time.time() - start_time

    print("=" * 90)
    print("PIPELINE FINISHED SUCCESSFULLY")
    print("=" * 90)
    print(f"Total elapsed: {elapsed_seconds:.2f} seconds")
    print()
    print("Main output files:")
    print(" - data/processed/stock_movements.csv")
    print(" - data/processed/monthly_inventory_balance.csv")
    print(" - data/processed/current_inventory_balance.csv")
    print(" - data/processed/company_monthly_inventory_summary.csv")
    print(" - data/processed/negative_inventory_alerts.csv")
    print(" - data/processed/duplicate_lotrols.csv")


if __name__ == "__main__":
    main()