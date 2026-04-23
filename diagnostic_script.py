import sys
import os
import time
import json
import requests
from app.services.vertex_config_store import get_vertex_config
from app.api.ai_suggestion_report import get_report_data, build_prompt

def run_diagnostics():
    # 2) Load config and print metadata
    try:
        config = get_vertex_config()
        api_key = config.get("api_key", "")
        model = config.get("model", "N/A")
        print(f"Config: model={model}, api_key_len={len(api_key)}")
    except Exception as e:
        print(f"Config error: {type(e).__name__}")

    # 3) Minimal xAI request
    try:
        url = "https://api.x.ai/v1/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        data = {
            "messages": [{"role": "user", "content": 'Return JSON {"ok":true}'}],
            "model": model,
            "max_tokens": 10
        }
        start_time = time.time()
        response = requests.post(url, headers=headers, json=data, timeout=60)
        elapsed = time.time() - start_time
        print(f"xAI Request: status={response.status_code}, elapsed={elapsed:.2f}s")
    except Exception as e:
        print(f"xAI Request error: {type(e).__name__}")

    # 4) Prompt size for job id 3b1b4ccb5b344051a973f5b89e5eb06d
    try:
        job_id = "3b1b4ccb5b344051a973f5b89e5eb06d"
        data = get_report_data(job_id)
        prompt = build_prompt(data)
        char_count = len(prompt)
        token_est = char_count / 4
        print(f"Prompt info: chars={char_count}, approx_tokens={token_est:.0f}")
    except Exception as e:
        print(f"Prompt size error: {type(e).__name__}")

if __name__ == "__main__":
    run_diagnostics()
