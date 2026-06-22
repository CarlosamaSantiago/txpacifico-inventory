from pathlib import Path
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_ZIP_PATH = PROJECT_ROOT / "data" / "raw" / "txpacifico.zip"
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"


def extract_zip() -> None:
    if not RAW_ZIP_PATH.exists():
        raise FileNotFoundError(f"ZIP file not found: {RAW_ZIP_PATH}")

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    with ZipFile(RAW_ZIP_PATH, "r") as zip_ref:
        zip_ref.extractall(EXTRACTED_DIR)

    print(f"ZIP extracted successfully to: {EXTRACTED_DIR}")


if __name__ == "__main__":
    extract_zip()