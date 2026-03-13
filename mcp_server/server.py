# -*- coding: utf-8 -*-
"""
Minimal MCP server example for the sanitized GitHub release.

Features:
- ping
- show_project_info
- run_full_pipeline

Usage:
    python mcp_server/server.py

Note:
This is a minimal example intended for open-source demonstration.
"""

from pathlib import Path
import subprocess
import sys

from fastmcp import FastMCP

BASE_DIR = Path(__file__).resolve().parents[1]
MAIN_FILE = BASE_DIR / 'main.py'
README_FILE = BASE_DIR / 'README.md'

mcp = FastMCP('weibo-local-image-filter')


@mcp.tool()
def ping() -> str:
    """Health check."""
    return 'pong'


@mcp.tool()
def show_project_info() -> str:
    """Return a short project summary."""
    return (
        'Weibo local image filtering project. '
        'Pipeline: crawl local Weibo posts -> download images -> face filtering -> young women recognition.'
    )


@mcp.tool()
def run_full_pipeline(pages: int = 3, interval: int = 0, threshold: float = 0.5) -> str:
    """
    Run the full local pipeline via main.py.
    Requires:
    - config.json
    - .env (recommended)
    - optional model weights for face classification
    """
    if not MAIN_FILE.exists():
        return f'main.py not found: {MAIN_FILE}'

    cmd = [
        sys.executable,
        str(MAIN_FILE),
        '--pages', str(pages),
        '--interval', str(interval),
        '--threshold', str(threshold),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=3600,
        )
        output = (result.stdout or '') + '\n' + (result.stderr or '')
        return f'Exit code: {result.returncode}\n\n{output[-8000:]}'
    except subprocess.TimeoutExpired:
        return 'Pipeline execution timed out.'
    except Exception as e:
        return f'Failed to run pipeline: {e}'


if __name__ == '__main__':
    mcp.run()
