#!/usr/bin/env bash
# OSS Guard launcher — works without activating venv
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python3" -m app.cli "$@"
