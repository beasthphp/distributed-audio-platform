import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError


app = FastAPI(
    title="Distributed Audio Upload API",
    version="1.0.0",
)


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIRECTORY = BASE_DIR / "storage"

AUDIO_DIRECTORY = STORAGE_DIRECTORY / "ready"
METADATA_DIRECTORY = STORAGE_DIRECTORY / "metadata"

AUDIO_DIRECTORY.mkdir(parents=True, exist_ok=True)
METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)


MAX_FILE_SIZE = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class AudioMetadata(BaseModel):
    """Metadata stored for every successfully uploaded audio file."""

    audio_id: str
    filename: str
    size_bytes: int
    status: str
    created_at: datetime
    stream_url: str


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
    """Validate an MP3, store it, and persist its metadata."""

    original_filename = file.filename or "unknown"
    extension = Path(original_filename).suffix.lower()

    if extension != ".mp3":
        await file.close()

        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only MP3 files are supported.",
        )

    audio_id = str(uuid4())

    audio_destination = AUDIO_DIRECTORY / f"{audio_id}.mp3"
    temporary_audio_destination = AUDIO_DIRECTORY / f"{audio_id}.part"

    metadata_destination = METADATA_DIRECTORY / f"{audio_id}.json"
    temporary_metadata_destination = (
        METADATA_DIRECTORY / f"{audio_id}.json.part"
    )

    total_bytes = 0

    try:
        # Save the uploaded audio incrementally.
        with temporary_audio_destination.open("wb") as output_file:
            while chunk := await file.read(CHUNK_SIZE):
                total_bytes += len(chunk)

                if total_bytes > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="The MP3 file exceeds the 50 MB size limit.",
                    )

                output_file.write(chunk)

        # The audio becomes ready only after the complete upload succeeds.
        temporary_audio_destination.replace(audio_destination)

        metadata = AudioMetadata(
            audio_id=audio_id,
            filename=original_filename,
            size_bytes=total_bytes,
            status="ready",
            created_at=datetime.now(timezone.utc),
            stream_url=f"/api/v1/audio/{audio_id}/stream",
        )

        # Save metadata using another temporary file.
        temporary_metadata_destination.write_text(
            metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )

        temporary_metadata_destination.replace(metadata_destination)

    except HTTPException:
        temporary_audio_destination.unlink(missing_ok=True)
        temporary_metadata_destination.unlink(missing_ok=True)
        audio_destination.unlink(missing_ok=True)
        metadata_destination.unlink(missing_ok=True)
        raise

    except OSError as error:
        temporary_audio_destination.unlink(missing_ok=True)
        temporary_metadata_destination.unlink(missing_ok=True)
        audio_destination.unlink(missing_ok=True)
        metadata_destination.unlink(missing_ok=True)

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
    """Retrieve metadata for an uploaded audio file."""

    try:
        normalized_audio_id = str(UUID(audio_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The audio ID is not a valid UUID.",
        ) from error

    audio_path = AUDIO_DIRECTORY / f"{normalized_audio_id}.mp3"
    metadata_path = METADATA_DIRECTORY / f"{normalized_audio_id}.json"

    if not audio_path.is_file() or not metadata_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file was not found.",
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