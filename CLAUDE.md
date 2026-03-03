# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A locally-runnable CLI tool that uses face recognition to filter a large photo library, finding photos that contain a specific target person. Built with InsightFace for face embedding and cosine similarity matching.

## Running the Script

```bash
cd gemini
python photo-filter.py
```

Before running, edit `CONFIG` at the top of `photo-filter.py` to set:
- `reference_dir` — directory of photos containing only the target person
- `source_dir` — root of the photo library to scan
- `output_dir` — where matched photos will be saved (auto-created)
- `threshold` — cosine similarity cutoff (0.4–0.55 typical; lower = more recall, higher = more precision)
- `debug` — set `True` for verbose per-image logging

## Dependencies

```bash
pip install opencv-python numpy tqdm insightface onnxruntime
```

InsightFace downloads the `buffalo_l` model on first run. The script uses `CPUExecutionProvider` (no GPU setup needed on Apple Silicon).

## Architecture

### `gemini/photo-filter.py` — single-file CLI

**`PhotoFilter` class:**
- `__init__`: Initializes InsightFace `FaceAnalysis` with `buffalo_l` model on CPU
- `build_reference_profile()`: Scans `reference_dir`, extracts face embeddings for each image, takes the largest face per image, then computes a mean normalized embedding as the target profile
- `process_photos()`: Walks `source_dir` recursively, runs face detection on each image, computes cosine similarity between each detected face and the target embedding, copies matches to `output_dir` preserving subdirectory structure
- `copy_file()`: Preserves the relative path from `source_dir` when copying to `output_dir`
- `get_embedding()`: Returns the embedding of the largest face in an image, or `None` if no face detected

**Face matching logic:** Embeddings are L2-normalized; cosine similarity is computed as a dot product. A photo is a match if any face in it exceeds `threshold`.

## Key Design Notes

- Supported formats: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.heic`
- For masked faces, 0.40–0.45 threshold is recommended; for clearer faces, 0.50–0.55
- Reference photos should contain only the target person (mixed masked/unmasked is fine)
- The `gemini/` directory name reflects the implementation origin; the project goal is a web UI version
