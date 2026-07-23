import argparse
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIRECTORY = BASE_DIR / "storage"

UPLOADS_DIRECTORY = STORAGE_DIRECTORY / "uploads"
METADATA_DIRECTORY = STORAGE_DIRECTORY / "metadata"
READY_DIRECTORY = STORAGE_DIRECTORY / "ready"

POLL_INTERVAL_SECONDS = 2
FFPROBE_TIMEOUT_SECONDS = 30
FFMPEG_TIMEOUT_SECONDS = 300


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class AudioProcessingError(Exception):
    """Raised when FFprobe or FFmpeg cannot process an audio file."""


def read_metadata(metadata_path: Path) -> dict[str, Any] | None:
    """Read a metadata JSON file."""

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


def validate_audio(source_path: Path) -> None:
    """Use FFprobe to confirm that the input contains audio."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
        check=False,
    )

    codec_name = result.stdout.strip()

    if result.returncode != 0 or not codec_name:
        error_message = result.stderr.strip()

        if not error_message:
            error_message = "No valid audio stream was found."

        raise AudioProcessingError(
            f"FFprobe validation failed: {error_message}"
        )

    logging.info(
        "FFprobe detected codec '%s' in %s",
        codec_name,
        source_path.name,
    )


def transcode_audio(
    source_path: Path,
    temporary_ready_path: Path,
) -> None:
    """Convert the source audio into a 128 kbps MP3."""

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:a:0",
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        str(temporary_ready_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )

    if result.returncode != 0:
        error_message = result.stderr.strip()

        if not error_message:
            error_message = "FFmpeg returned a non-zero exit code."

        raise AudioProcessingError(
            f"FFmpeg processing failed: {error_message}"
        )

    if not temporary_ready_path.is_file():
        raise AudioProcessingError(
            "FFmpeg completed without creating an output file."
        )

    if temporary_ready_path.stat().st_size == 0:
        raise AudioProcessingError(
            "FFmpeg created an empty output file."
        )


def process_job(metadata_path: Path) -> bool:
    """Validate and transcode one queued audio job."""

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
            raise AudioProcessingError(
                "The uploaded source file does not exist."
            )

        validate_audio(source_path)

        transcode_audio(
            source_path=source_path,
            temporary_ready_path=temporary_ready_path,
        )

        os.replace(
            temporary_ready_path,
            ready_path,
        )

    except (
        AudioProcessingError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        temporary_ready_path.unlink(missing_ok=True)
        ready_path.unlink(missing_ok=True)

        metadata["status"] = "failed"
        metadata["error"] = str(error)

        write_metadata(metadata_path, metadata)

        logging.error(
            "Audio job %s failed: %s",
            audio_id,
            error,
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

    logging.info("Audio processing worker started")
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
        description="Validate and process queued audio uploads."
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
        logging.info("Audio processing worker stopped")


if __name__ == "__main__":
    main()