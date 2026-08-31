# Distributed Audio Processing & Streaming Platform

A backend-focused audio platform that accepts MP3 uploads through FastAPI, processes them asynchronously with FFprobe and FFmpeg, tracks job state on disk, and serves ready audio through a C++ HTTP streaming server.

The project is intentionally small enough to understand end-to-end while demonstrating service separation, background processing, safe file handling, media validation/transcoding, and HTTP streaming.

## Architecture

```text
Client
  |
  | POST /api/v1/audio
  v
FastAPI Upload Service
  |
  | stores original.mp3 + metadata
  | status: queued
  v
Persistent Local Storage
  |
  v
Python Worker
  |
  +--> FFprobe validation
  +--> FFmpeg transcoding -> 128 kbps MP3
  |
  | status: processing -> ready / failed
  v
Ready Audio Storage
  |
  v
C++ HTTP Streaming Server
  |
  | GET /api/v1/audio/{audio_id}/stream
  v
Seekable MP3 Playback
```

## What It Demonstrates

- **FastAPI upload API** for MP3 ingestion and job-status lookup
- **Chunked uploads** so files are not loaded fully into memory
- **50 MB upload limit** with validation and cleanup on failure
- **Atomic file and metadata writes** using temporary files followed by rename/replace
- **Persistent JSON job metadata** with `queued`, `processing`, `ready`, and `failed` states
- **Background Python worker** that continuously discovers queued jobs
- **FFprobe validation** to verify that an uploaded file contains a valid audio stream
- **FFmpeg transcoding** into a standardized 128 kbps MP3 output
- **C++17 HTTP server** for serving processed audio
- **HTTP byte-range friendly responses** with `Accept-Ranges: bytes` for seekable playback
- **UUID-based file lookup** to avoid arbitrary filesystem paths from requests
- Separate upload/processing and streaming responsibilities

## Request Flow

1. A client uploads an `.mp3` file to `POST /api/v1/audio`.
2. The API creates a UUID for the audio job.
3. The file is written in chunks to a temporary `.part` file.
4. After the upload completes successfully, the temporary file is atomically renamed to `original.mp3`.
5. JSON metadata is stored with status `queued`.
6. The Python worker discovers the queued job and changes its status to `processing`.
7. FFprobe verifies that the file contains a usable audio stream.
8. FFmpeg converts the source into a 128 kbps MP3.
9. The processed file is atomically moved into the ready-audio directory.
10. Metadata changes to `ready` or `failed` if processing encounters an error.
11. The C++ server exposes the processed MP3 through `/api/v1/audio/{audio_id}/stream`.

## API

### Upload service

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Upload-service health check |
| `POST` | `/api/v1/audio` | Upload an MP3 and create a processing job |
| `GET` | `/api/v1/audio/{audio_id}` | Read the current job state |

Example upload:

```bash
curl -X POST \
  -F "file=@example.mp3" \
  http://127.0.0.1:8000/api/v1/audio
```

Example response:

```json
{
  "audio_id": "3e11dc79-80ce-4a24-b9b5-66db5dfda01f",
  "filename": "example.mp3",
  "size_bytes": 4213376,
  "status": "queued",
  "error": null
}
```

Check processing state:

```bash
curl http://127.0.0.1:8000/api/v1/audio/<audio_id>
```

### Streaming service

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Streaming-server health check |
| `GET` | `/api/v1/audio/{audio_id}/stream` | Stream a ready MP3 |

Example:

```bash
curl -I http://127.0.0.1:8080/api/v1/audio/<audio_id>/stream
```

The streaming response uses `audio/mpeg` and advertises byte-range support with:

```text
Accept-Ranges: bytes
```

## Job State Machine

```text
              +------------+
              |   queued   |
              +-----+------+
                    |
                    v
              +------------+
              | processing |
              +-----+------+
                    |
             +------+------+
             |             |
             v             v
        +---------+    +--------+
        |  ready  |    | failed |
        +---------+    +--------+
```

A failed job stores the processing error in its metadata so the failure can be inspected through the status API.

## Repository Structure

```text
.
├── upload-api/
│   ├── app/
│   │   └── main.py          # FastAPI upload and status API
│   ├── storage/
│   │   ├── uploads/         # Original uploads, grouped by UUID
│   │   ├── metadata/        # Persistent job-state JSON files
│   │   └── ready/           # Processed 128 kbps MP3 files
│   ├── requirements.txt
│   └── worker.py            # FFprobe + FFmpeg background processor
│
└── stream-server/
    ├── src/
    │   └── main.cpp         # C++ HTTP streaming server
    ├── third_party/         # Header-only HTTP dependency
    └── CMakeLists.txt
```

## Tech Stack

| Area | Technology |
| --- | --- |
| Upload API | Python, FastAPI, Uvicorn |
| Background processing | Python |
| Media validation | FFprobe |
| Audio transcoding | FFmpeg / libmp3lame |
| Streaming server | C++17, cpp-httplib |
| Build system | CMake |
| Metadata | JSON |
| Storage | Local filesystem |

## Running Locally

### Requirements

Install:

- Python 3.11+
- FFmpeg and FFprobe available on `PATH`
- CMake 3.20+
- A C++17 compiler

### 1. Start the upload API

```bash
cd upload-api
python -m venv .venv
```

Activate the environment and install dependencies:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Start the audio worker

In another terminal:

```bash
cd upload-api
python worker.py
```

To process only the jobs currently queued and then exit:

```bash
python worker.py --once
```

### 3. Build the C++ streaming server

```bash
cd stream-server
cmake -S . -B build
cmake --build build --config Release
```

Before starting the server, set `AUDIO_STORAGE_DIR` to the absolute path of:

```text
upload-api/storage/ready
```

The stream server listens on:

```text
http://127.0.0.1:8080
```

## Engineering Decisions

### Chunked upload handling

The FastAPI endpoint reads files in 1 MB chunks instead of loading the complete MP3 into memory. This keeps memory usage bounded for supported uploads.

### Atomic writes

Uploads, transcoded files, and metadata are first written to temporary `.part` files. They are renamed only after the operation succeeds, reducing the chance that another component observes a partially written file.

### Persistent job state

The prototype deliberately uses JSON metadata instead of adding a database or message broker. That keeps the processing lifecycle visible and easy to inspect while still demonstrating a durable job state across process restarts.

### Media validation before transcoding

A `.mp3` extension alone does not prove that a file contains valid audio. The worker therefore uses FFprobe before FFmpeg processing.

### Separate C++ streaming service

Streaming is kept outside the Python upload service so the project can explore HTTP delivery and systems programming independently from the API and processing pipeline.

## Current Scope

This is a working prototype rather than a production audio platform. It currently uses filesystem-backed storage and polling rather than Redis/Kafka or a distributed job queue. Authentication, object storage, CDN delivery, multi-node coordination, and production observability are outside the current implementation.

## Future Work

- Replace polling with a durable queue such as Redis Streams or RabbitMQ
- Move processed audio to S3-compatible object storage
- Add authentication and per-user ownership
- Add structured metrics and monitoring
- Containerize the services
- Add automated integration tests for upload -> processing -> streaming
- Add concurrency and streaming benchmarks
- Deploy upload and streaming services independently behind Nginx

## Interview Summary

**One-line explanation:**

> I built an audio backend where FastAPI accepts MP3 uploads, a Python worker validates and transcodes them with FFprobe/FFmpeg, persistent metadata tracks each job through queued/processing/ready/failed states, and a C++ HTTP server serves the processed files for seekable playback.
