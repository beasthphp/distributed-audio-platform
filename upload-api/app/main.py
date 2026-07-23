import json
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError


app = FastAPI(
    title="Distributed Audio Upload API",
    version="2.0.0",
)


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIRECTORY = BASE_DIR / "storage"

UPLOADS_DIRECTORY = STORAGE_DIRECTORY / "uploads"
METADATA_DIRECTORY = STORAGE_DIRECTORY / "metadata"
READY_DIRECTORY = STORAGE_DIRECTORY / "ready"

UPLOADS_DIRECTORY.mkdir(parents=True, exist_ok=True)
METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
READY_DIRECTORY.mkdir(parents=True, exist_ok=True)


MAX_FILE_SIZE = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class AudioMetadata(BaseModel):
    """Metadata stored for each uploaded audio file."""

    audio_id: str
    filename: str
    size_bytes: int
    status: Literal["queued", "processing", "ready", "failed"]
    error: str | None = None


def cleanup_failed_upload(
    upload_directory: Path,
    temporary_audio_path: Path,
    audio_path: Path,
    temporary_metadata_path: Path,
    metadata_path: Path,
) -> None:
    """Remove files created during an unsuccessful upload."""

    temporary_audio_path.unlink(missing_ok=True)
    audio_path.unlink(missing_ok=True)
    temporary_metadata_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)

    try:
        upload_directory.rmdir()
    except OSError:
        pass


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "service": "upload-api",
        "status": "healthy",
    }


@app.post(
    "/api/v1/audio",
    response_model=AudioMetadata,
    status_code=status.HTTP_201_CREATED,
)
async def upload_audio(
    file: UploadFile = File(...),
) -> AudioMetadata:
    """Validate an MP3, store the original file, and queue it."""

    original_filename = file.filename or "unknown"
    extension = Path(original_filename).suffix.lower()

    if extension != ".mp3":
        await file.close()

        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only MP3 files are supported.",
        )

    audio_id = str(uuid4())

    upload_directory = UPLOADS_DIRECTORY / audio_id

    audio_destination = upload_directory / "original.mp3"
    temporary_audio_destination = upload_directory / "original.mp3.part"

    metadata_destination = METADATA_DIRECTORY / f"{audio_id}.json"
    temporary_metadata_destination = (
        METADATA_DIRECTORY / f"{audio_id}.json.part"
    )

    total_bytes = 0

    try:
        upload_directory.mkdir(parents=True, exist_ok=False)

        # Save the upload in chunks instead of loading the entire file
        # into memory.
        with temporary_audio_destination.open("wb") as output_file:
            while chunk := await file.read(CHUNK_SIZE):
                total_bytes += len(chunk)

                if total_bytes > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="The MP3 file exceeds the 50 MB size limit.",
                    )

                output_file.write(chunk)

        # Rename only after the complete upload succeeds.
        temporary_audio_destination.replace(audio_destination)

        metadata = AudioMetadata(
            audio_id=audio_id,
            filename=original_filename,
            size_bytes=total_bytes,
            status="queued",
            error=None,
        )

        # Write metadata through a temporary file to avoid partially
        # written JSON.
        temporary_metadata_destination.write_text(
            metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )

        temporary_metadata_destination.replace(metadata_destination)

    except HTTPException:
        cleanup_failed_upload(
            upload_directory=upload_directory,
            temporary_audio_path=temporary_audio_destination,
            audio_path=audio_destination,
            temporary_metadata_path=temporary_metadata_destination,
            metadata_path=metadata_destination,
        )
        raise

    except OSError as error:
        cleanup_failed_upload(
            upload_directory=upload_directory,
            temporary_audio_path=temporary_audio_destination,
            audio_path=audio_destination,
            temporary_metadata_path=temporary_metadata_destination,
            metadata_path=metadata_destination,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The server could not store the uploaded audio.",
        ) from error

    finally:
        await file.close()

    return metadata


@app.get(
    "/api/v1/audio/{audio_id}",
    response_model=AudioMetadata,
)
def get_audio_metadata(audio_id: str) -> AudioMetadata:
    """Retrieve the current processing status of an audio file."""

    try:
        normalized_audio_id = str(UUID(audio_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The audio ID is not a valid UUID.",
        ) from error

    metadata_path = METADATA_DIRECTORY / f"{normalized_audio_id}.json"

    if not metadata_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio metadata was not found.",
        )

    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = AudioMetadata.model_validate_json(metadata_text)

    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored audio metadata could not be read.",
        ) from error

    return metadata