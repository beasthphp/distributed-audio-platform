# Upload API and processing worker

This directory contains the ingestion and processing side of the audio platform.

## Upload API

The FastAPI service accepts MP3 uploads, writes files in chunks, enforces the configured size limit, stores persistent JSON job metadata, and exposes job-status lookup endpoints.

Job states are:

```text
queued -> processing -> ready
                    \-> failed
```

## Processing worker

`worker.py` polls queued jobs, validates uploaded media with FFprobe, transcodes valid input to standardized 128 kbps MP3 with FFmpeg, and writes the processed asset into `storage/ready/`.

File and metadata writes use temporary `.part` files followed by atomic replacement so partially written output is not exposed as complete work.

## Local development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In a second terminal:

```bash
python worker.py
```
