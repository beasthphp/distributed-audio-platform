import argparse
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIRECTORY = BASE_DIR / "storage"

UPLOADS_DIRECTORY = STORAGE_DIRECTORY / "uploads"
METADATA_DIRECTORY = STORAGE_DIRECTORY / "metadata"
READY_DIRECTORY = STORAGE_DIRECTORY / "ready"

POLL_INTERVAL_SECONDS = 2


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def read_metadata(metadata_path: Path) -> dict[str, Any] | None:
    """Read and validate a metadata JSON file."""

    try:
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        logging.exception(
            "Could not read metadata file: %s",
            metadata_path.name,
        )
        return None

    if not isinstance(metadata, dict):
        logging.error(
            "Metadata is not a JSON object: %s",
            metadata_path.name,
        )
        return None

    return metadata


def write_metadata(
    metadata_path: Path,
    metadata: dict[str, Any],
) -> None:
    """Write metadata atomically using a temporary file."""

    temporary_path = metadata_path.with_suffix(".json.part")

    temporary_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    os.replace(temporary_path, metadata_path)


def process_job(metadata_path: Path) -> bool:
    """Process one queued audio job."""

    metadata = read_metadata(metadata_path)

    if metadata is None:
        return False

    if metadata.get("status") != "queued":
        return False

    audio_id = metadata.get("audio_id")

    if not isinstance(audio_id, str) or metadata_path.stem != audio_id:
        logging.error(
            "Invalid audio ID in metadata file: %s",
            metadata_path.name,
        )
        return False

    source_path = (
        UPLOADS_DIRECTORY
        / audio_id
        / "original.mp3"
    )

    ready_path = READY_DIRECTORY / f"{audio_id}.mp3"
    temporary_ready_path = READY_DIRECTORY / f"{audio_id}.mp3.part"

    logging.info("Processing audio job %s", audio_id)

    metadata["status"] = "processing"
    metadata["error"] = None
    write_metadata(metadata_path, metadata)

    try:
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Uploaded audio does not exist: {source_path}"
            )

        shutil.copyfile(
            source_path,
            temporary_ready_path,
        )

        os.replace(
            temporary_ready_path,
            ready_path,
        )

    except (OSError, shutil.Error):
        temporary_ready_path.unlink(missing_ok=True)
        ready_path.unlink(missing_ok=True)

        metadata["status"] = "failed"
        metadata["error"] = "Worker could not copy the uploaded audio."

        write_metadata(metadata_path, metadata)

        logging.exception(
            "Audio job %s failed",
            audio_id,
        )

        return True

    metadata["status"] = "ready"
    metadata["error"] = None

    write_metadata(metadata_path, metadata)

    logging.info("Audio job %s is ready", audio_id)

    return True


def process_queued_jobs() -> int:
    """Find and process all currently queued jobs."""

    processed_count = 0

    for metadata_path in sorted(
        METADATA_DIRECTORY.glob("*.json")
    ):
        if process_job(metadata_path):
            processed_count += 1

    return processed_count


def run_worker() -> None:
    """Continuously look for queued audio jobs."""

    UPLOADS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    READY_DIRECTORY.mkdir(parents=True, exist_ok=True)

    logging.info("Audio worker started")
    logging.info(
        "Checking for queued jobs every %s seconds",
        POLL_INTERVAL_SECONDS,
    )

    while True:
        processed_count = process_queued_jobs()

        if processed_count == 0:
            time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process queued audio uploads."
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Process current queued jobs and exit.",
    )

    arguments = parser.parse_args()

    if arguments.once:
        processed_count = process_queued_jobs()

        logging.info(
            "Processed %s queued job(s)",
            processed_count,
        )
        return

    try:
        run_worker()
    except KeyboardInterrupt:
        logging.info("Audio worker stopped")


if __name__ == "__main__":
    main()