import sys, os, time, json, urllib.request, urllib.error
sys.path.append(os.getcwd())
try:
    from app.services.vertex_config_store import get_vertex_config
    from app.services.ai_suggestion_report import get_report_data, build_prompt
    config = get_vertex_config()
    api_key = getattr(config, 'api_key', config.get('api_key', ''))
    model = getattr(config, 'model', config.get('model', 'N/A'))
    print(f"Config: model={model}, api_key_len={len(api_key)}")
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {"messages": [{"role": "user", "content": 'Return JSON {"ok":true}'}], "model": model, "max_tokens": 10}
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method='POST')
    st = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"xAI Request: status={resp.getcode()}, elapsed={time.time()-st:.2f}s")
    except urllib.error.HTTPError as e:
        print(f"xAI Request: status={e.code}, elapsed={time.time()-st:.2f}s")
    except Exception as e:
        print(f"xAI Request error: {type(e).__name__}")
    job_id = "3b1b4ccb5b344051a973f5b89e5eb06d"
    rep_data = get_report_data(job_id)
    prompt = build_prompt(rep_data)
    print(f"Prompt info: chars={len(prompt)}, approx_tokens={len(prompt)/4:.0f}")
except Exception as e:
    import traceback
    traceback.print_exc()
