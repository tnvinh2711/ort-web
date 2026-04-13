# ORT Local Visualizer

Website local bằng Python để visualize toàn bộ chức năng OSS Review Toolkit (ORT), có khả năng chạy command ORT thật, theo dõi log realtime và duyệt artifacts.

## Stack

- FastAPI
- Jinja2 + HTMX
- SQLite (job state)
- SSE (stream log realtime)

## Quick Start

1. Tao va kich hoat virtual environment.
2. Cai dependencies:

```bash
pip install -e .
```

3. Chay app:

```bash
uvicorn app.main:app --reload
```

4. Mo trinh duyet: http://127.0.0.1:8000

## Notes

- App chay local-first, khong co auth trong ban dau.
- De chay ORT commands, can cai dat ORT binary (`ort`) trong PATH.
- Du lieu runtime duoc ghi vao `runtime/`.

## Cross-platform support

- macOS: duoc ho tro.
- Windows: duoc ho tro.

Ban co the cai ORT ngay trong UI bang nut `Install ORT (macOS / Windows)` tren Dashboard.
Installer se cai vao thu muc mac dinh theo OS:

- macOS: `/opt/homebrew/bin` (neu co) hoac `/usr/local/bin`
- Windows: `%LOCALAPPDATA%\Programs\ORT\bin`

Neu thu muc mac dinh khong ghi duoc, he thong se fallback ve `~/.local/bin`.
