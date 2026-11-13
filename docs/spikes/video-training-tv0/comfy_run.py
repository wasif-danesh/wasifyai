import json, sys, time, uuid, urllib.request, glob, os, subprocess
BASE = "http://127.0.0.1:8301"
W = json.load(open("/Users/wasifdanesh/Projects/wasifyai/products/wasifyai-video/workflows/ltx-video-2b-t2v.json"))
PROMPT = "zqx7 style, a slow spiral of teal and magenta light drifting over a deep navy background"
def build(lora=None, strength=1.0, cfg=3.0, seed=7, w=384, h=256, length=25, steps=30, prompt=PROMPT):
    g = json.loads(json.dumps(W))
    g["6"]["inputs"]["text"] = prompt; g["77"]["inputs"].update(width=w, height=h, length=length); g["71"]["inputs"]["steps"] = steps
    g["72"]["inputs"].update(noise_seed=seed, cfg=cfg); g["81"]["inputs"]["filename_prefix"] = f"tv0/{lora or 'base'}_{strength}_{cfg}_{seed}".replace(".safetensors", "")
    if lora:
        g["90"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["44", 0], "lora_name": lora, "strength_model": strength}}
        g["72"]["inputs"]["model"] = ["90", 0]
    return g
def run(g):
    t0 = time.time()
    req = urllib.request.Request(f"{BASE}/prompt", data=json.dumps({"prompt": g, "client_id": uuid.uuid4().hex}).encode(), headers={"Content-Type": "application/json"})
    try: pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    except urllib.error.HTTPError as e: raise SystemExit("rejected: " + e.read().decode()[:1500])
    while True:
        h = json.load(urllib.request.urlopen(f"{BASE}/history/{pid}"))
        if pid in h:
            st = h[pid]["status"]
            if st.get("status_str") == "error": raise SystemExit("error: " + json.dumps(st.get("messages"))[:1500])
            outs = [(n.get("filename"), n.get("subfolder")) for node in h[pid]["outputs"].values() for n in node.get("images", [])]
            return outs, time.time() - t0
        time.sleep(1)
if __name__ == "__main__":
    cases = json.loads(sys.argv[1])
    for c in cases:
        outs, dt = run(build(**c)); print(c, "->", outs, f"{dt:.0f}s", flush=True)
