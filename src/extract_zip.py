from pathlib import Path
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_ZIP_PATH = PROJECT_ROOT / "data" / "raw" / "txpacifico.zip"
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"


def extract_zip() -> None:
    if not RAW_ZIP_PATH.exists():
        raise FileNotFoundError(f"ZIP file not found: {RAW_ZIP_PATH}")

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    extracted_count = 0
    skipped_count = 0

    with ZipFile(RAW_ZIP_PATH, "r") as zip_ref:
        for member in zip_ref.infolist():
            target_path = EXTRACTED_DIR / member.filename

            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            if target_path.exists():
                skipped_count += 1
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            zip_ref.extract(member, EXTRACTED_DIR)
            extracted_count += 1

    print(f"ZIP extracted successfully to: {EXTRACTED_DIR}")
    print(f"Files extracted: {extracted_count:,}")
    print(f"Existing files skipped: {skipped_count:,}")


if __name__ == "__main__":
    extract_zip()
