# MCP Server Example

This directory contains a **minimal runnable MCP server example** for the project.

## Provided tools

- `ping`
- `show_project_info`
- `run_full_pipeline`

## Purpose

This server is intended as a lightweight demonstration of how the project can be exposed as an agent-friendly tool layer.

## Requirements

Before running:

1. Install dependencies:

```bash
pip install -r ../requirements.txt
```

2. Prepare configuration:

- copy `../.env.example` to `../.env`
- copy `../config.example.json` to `../config.json`
- fill real values

3. Optional: place face model weights at:

```text
../classification/face_classifier.pth
```

## Run

```bash
python server.py
```

## Notes

- This is a minimal demo server, not a full production MCP deployment.
- You can extend it by splitting the pipeline into multiple tools:
  - fetch_weibo_local_posts
  - download_weibo_images
  - classify_face_images
  - recognize_young_women
