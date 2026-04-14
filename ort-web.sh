#!/usr/bin/env bash
# ORT Web launcher — works without activating venv
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python3" -m app.cli "$@"
