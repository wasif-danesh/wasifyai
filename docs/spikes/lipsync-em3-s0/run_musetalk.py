"""MuseTalk on the same inputs, through the app's own engine wrapper, timed."""
import json, resource, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])  # lipsync_server dir
import torch
from engine import Engine
img, voice, out = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
peak = [0]; stop = [False]
def poll():
    while not stop[0]:
        peak[0] = max(peak[0], torch.mps.driver_allocated_memory()); time.sleep(0.25)
threading.Thread(target=poll, daemon=True).start()
e = Engine(); t0 = time.monotonic(); e.load(); load = time.monotonic() - t0
t1 = time.monotonic(); mp4 = e.generate(img.read_bytes(), voice, 25, 8); work = time.monotonic() - t1
stop[0] = True; out.write_bytes(mp4)
import subprocess
secs = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(out)],capture_output=True,text=True).stdout)
r = {"image": img.name, "audio": Path(voice).name, "video_s": round(secs,2), "load_s": round(load,1), "work_s": round(work,1),
     "work_per_video_s": round(work/secs,1), "peak_gpu_gb": round(peak[0]/1e9,2), "max_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9,2)}
print(json.dumps(r)); out.with_suffix(".json").write_text(json.dumps(r, indent=1))
