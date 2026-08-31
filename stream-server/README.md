# C++ audio streaming server

This service is the delivery layer of the audio platform. It serves processed MP3 files from the shared ready-audio directory through a small C++17 HTTP server.

Key responsibilities:

- validate audio IDs before filesystem access
- locate processed `{audio_id}.mp3` assets
- expose a health endpoint
- advertise byte-range support for seekable playback
- return audio as `audio/mpeg`

The server intentionally stays separate from upload and transcoding work so media processing and playback delivery can evolve independently.

## Run

Set the processed-audio directory before starting the server:

```bash
AUDIO_STORAGE_DIR=/path/to/upload-api/storage/ready ./audio_stream_server
```

The default listener is `127.0.0.1:8080`.
