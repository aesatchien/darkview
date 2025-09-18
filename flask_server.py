# flask_server_v7.py  - 20250906 CJH + GPT
#
# Adds: /record_10s button, background MP4 recorder, and live recording status bar.
# Keeps the original interface expected by main.py: app, update_cam1/2/fusion, current_mode.
#
# References to existing structure:
# - Uses the same shared dicts and keys used by /stream (outlined, fused_with_outline)  [flask_server.py] :contentReference[oaicite:3]{index=3}
# - Reuses cam2 exposure tuner and view-queue strategy                                   [camera_control.py] :contentReference[oaicite:4]{index=4}
# - Cooperates with the main feeder thread that updates these dicts                      [main.py] :contentReference[oaicite:5]{index=5}

from flask import Flask, Response, render_template_string, request, jsonify
import threading
import time
import cv2
import os
from datetime import datetime
import logging

from camera_control import auto_exposure_tune
from shared_state import cam2, cam2_view_queue

app = Flask(__name__)


# quiet down the logging whether we are recording or not
class _IgnoreRecordStatus(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # skip werkzeug access log lines for /record_status
        return ('GET /record_status' not in msg) and ('POST /record_status' not in msg)


logging.getLogger('werkzeug').addFilter(_IgnoreRecordStatus())

# ---------------- Shared state (unchanged for /stream consumers) ----------------
cam1_data = {}
cam2_data = {}
fusion_data = {}
data_lock = threading.Lock()

# Mode can be 'cam1', 'cam2', 'fusion'
current_mode = {'view': 'cam1'}

# ---------------- Recording state ----------------
recording_lock = threading.Lock()
record_state = {
    'active': False,
    't_start': 0.0,
    'duration': 10.0,
    'fps': 30,
    'filename': None
}
raw_record_lock = threading.Lock()
raw_record_state = {
    'active': False,
    't_start': 0.0,
    'duration': 10.0,
    'fps': 30,
    'filenames': {'cam1': None, 'cam2': None}
}


# ---------------- HTML (now rendered by function to inject status) ----------------
def render_page():
    # If recording, show a status bar that updates via /record_status polling
    status_block = """
<div id="rec-wrap" style="margin-top:10px; display:none;">
  <div style="font-weight:bold; margin-bottom:4px;">Recording...</div>
  <div style="width:260px; height:18px; background:#ddd;">
    <div id="rec-bar" style="width:100%; height:100%; background:#c00;"></div>
  </div>
  <div id="rec-text" style="margin-top:4px; font-family:monospace;"></div>
</div>
<div id="rec-raw-wrap" style="margin-top:10px; display:none;">
  <div style="font-weight:bold; margin-bottom:4px;">Recording RAW (cam1 + cam2)...</div>
  <div style="width:260px; height:18px; background:#ddd;">
    <div id="rec-raw-bar" style="width:100%; height:100%; background:#060;"></div>
  </div>
  <div id="rec-raw-text" style="margin-top:4px; font-family:monospace;"></div>
</div>

<script>
(function(){
  const wrap = document.getElementById('rec-wrap');
  const bar  = document.getElementById('rec-bar');
  const txt  = document.getElementById('rec-text');
  const wrapR = document.getElementById('rec-raw-wrap');
  const barR  = document.getElementById('rec-raw-bar');
  const txtR  = document.getElementById('rec-raw-text');

  function poll(){
    fetch('/record_status').then(r=>r.json()).then(s=>{
      // display (existing)
      if(s.display.active){
        wrap.style.display = 'block';
        const pct = Math.max(0, Math.min(100, 100 * s.display.remaining / s.display.duration));
        bar.style.width = pct + '%';
        txt.textContent = `Remaining: ${s.display.remaining.toFixed(1)}s  →  ${s.display.filename || ''}`;
      } else {
        wrap.style.display = 'none';
      }

      // raw (new)
      if(s.raw.active){
        wrapR.style.display = 'block';
        const pctR = Math.max(0, Math.min(100, 100 * s.raw.remaining / s.raw.duration));
        barR.style.width = pctR + '%';
        const f1 = s.raw.filenames?.cam1 || '';
        const f2 = s.raw.filenames?.cam2 || '';
        txtR.textContent = `Remaining: ${s.raw.remaining.toFixed(1)}s  →  cam1: ${f1}   cam2: ${f2}`;
      } else {
        wrapR.style.display = 'none';
      }

      // adaptive poll rate
      const active = s.display.active || s.raw.active;
      setTimeout(poll, active ? 500 : 2500);
    }).catch(()=>setTimeout(poll, 3000));
  }
  poll();
})();
</script>

"""
    return f"""
<!doctype html>
<html>
<head>
  <title>Camera Fusion Viewer</title>
</head>
<body>
  <h2>Darkview Camera Live Stream</h2>
<form method="get" action="/set_mode" style="display: flex; align-items: center; gap: 10px;">
  <div>
    <button name="view" value="cam1">Cam1 (Blue Outline)</button>
    <button name="view" value="cam2">Cam2 (Red Outline)</button>
    <button name="view" value="fusion">Fusion</button>
  </div>
  <div style="margin-left: 60px;">
    <button formaction="/tune_cam2_exposure" type="submit">Auto Tune Cam2 Exposure</button>
  </div>
  <div style="margin-left: 60px;">
    <button formaction="/record_10s" type="submit">Record 10s Clip</button>
  </div>
  <div style="margin-left: 60px;">
    <button formaction="/record_raw_both_10s" type="submit">Record 10s RAW (cam1+cam2)</button>
  </div>
</form>
  {status_block}
  <img src="/stream" width="1280" height="720">
</body>
</html>
"""

# ---------------- Routes ----------------

@app.route('/')
def index():
    return render_template_string(render_page())

@app.route('/set_mode')
def set_mode():
    view = request.args.get('view', 'cam1')
    if view in ['cam1', 'cam2', 'fusion']:
        current_mode['view'] = view
        print(f"[Flask] Switched to view: {view}")
    return render_template_string(render_page())

@app.route('/tune_cam2_exposure')
def tune_cam2_exposure():
    # Pause cam2 capture while we probe from the view queue
    cam2.pause_capture.set()
    try:
        auto_exposure_tune(cam2.device, cam2_view_queue)
    finally:
        cam2.pause_capture.clear()
    return render_template_string(render_page())

@app.route('/stream')
def stream():
    def gen():
        while True:
            with data_lock:
                mode = current_mode['view']
                if mode == 'cam1':
                    frame = cam1_data.get('outlined')
                elif mode == 'cam2':
                    frame = cam2_data.get('outlined')
                elif mode == 'fusion':
                    frame = fusion_data.get('fused_with_outline')
                else:
                    frame = None
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            time.sleep(0.001)  # ~30 FPS cap
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ---------------- Recording implementation ----------------

def _record_current_view(duration_s=10.0, target_fps=30):
    os.makedirs("clips", exist_ok=True)

    with data_lock:
        mode = current_mode['view']
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join("clips", f"{mode}_{ts}.mp4")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = None
    frames_written = 0
    dt = 1.0 / float(target_fps)
    t0 = time.time()

    # Update shared recording state
    with recording_lock:
        record_state.update({
            'active': True,
            't_start': t0,
            'duration': float(duration_s),
            'fps': int(target_fps),
            'filename': out_path
        })

    try:
        while True:
            # Stop when time is up
            if time.time() - t0 >= duration_s:
                break

            # Snapshot current frame from shared dicts
            with data_lock:
                mode = current_mode['view']
                if mode == 'cam1':
                    frame = cam1_data.get('outlined')
                elif mode == 'cam2':
                    frame = cam2_data.get('outlined')
                else:
                    frame = fusion_data.get('fused_with_outline')

            if frame is not None:
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(out_path, fourcc, target_fps, (w, h))
                    if not writer.isOpened():
                        print(f"[Recorder] Failed to open writer for {out_path}")
                        break

                # Ensure BGR
                if len(frame.shape) == 2:
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                else:
                    frame_bgr = frame
                writer.write(frame_bgr)
                frames_written += 1

            time.sleep(dt)

        print(f"[Recorder] Saved {frames_written} frames to {out_path}")
    except Exception as e:
        print(f"[Recorder] Error: {e}")
    finally:
        if writer is not None:
            writer.release()
        with recording_lock:
            record_state['active'] = False

def _record_raw_both_10s(duration_s=10.0, target_fps=30):
    """
    Records cam1 and cam2 RAW streams simultaneously into two MP4s.
    Latches each writer's size from its first valid raw frame.
    """
    os.makedirs("clips", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_cam1 = os.path.join("clips", f"cam1_raw_{ts}.mp4")
    out_cam2 = os.path.join("clips", f"cam2_raw_{ts}.mp4")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    w1 = w2 = None
    h1 = h2 = None
    writer1 = writer2 = None
    frames1 = frames2 = 0
    dt = 1.0 / float(target_fps)
    t0 = time.time()

    # Arm shared state
    with raw_record_lock:
        raw_record_state.update({
            'active': True,
            't_start': t0,
            'duration': float(duration_s),
            'fps': int(target_fps),
            'filenames': {'cam1': out_cam1, 'cam2': out_cam2}
        })

    try:
        # small start window to get first frames
        start_deadline = t0 + 2.0  # up to 2s to see first raw frames
        while (w1 is None or w2 is None) and time.time() < start_deadline:
            with data_lock:
                f1 = cam1_data.get('raw')
                f2 = cam2_data.get('raw')
            if w1 is None and f1 is not None:
                h1, w1 = f1.shape[:2]
                writer1 = cv2.VideoWriter(out_cam1, fourcc, target_fps, (w1, h1))
                if not writer1.isOpened():
                    print(f"[RawRec] Failed to open writer for {out_cam1}"); writer1 = None; w1 = None
            if w2 is None and f2 is not None:
                h2, w2 = f2.shape[:2]
                writer2 = cv2.VideoWriter(out_cam2, fourcc, target_fps, (w2, h2))
                if not writer2.isOpened():
                    print(f"[RawRec] Failed to open writer for {out_cam2}"); writer2 = None; w2 = None
            time.sleep(0.02)

        # timed loop
        while (time.time() - t0) < duration_s:
            with data_lock:
                f1 = cam1_data.get('raw')
                f2 = cam2_data.get('raw')

            if writer1 is not None and f1 is not None:
                fb1 = cv2.cvtColor(f1, cv2.COLOR_GRAY2BGR) if f1.ndim == 2 else f1
                if fb1.shape[1] != w1 or fb1.shape[0] != h1:
                    fb1 = cv2.resize(fb1, (w1, h1))
                writer1.write(fb1); frames1 += 1

            if writer2 is not None and f2 is not None:
                fb2 = cv2.cvtColor(f2, cv2.COLOR_GRAY2BGR) if f2.ndim == 2 else f2
                if fb2.shape[1] != w2 or fb2.shape[0] != h2:
                    fb2 = cv2.resize(fb2, (w2, h2))
                writer2.write(fb2); frames2 += 1

            time.sleep(dt)

        print(f"[RawRec] Saved cam1:{frames1} → {out_cam1} | cam2:{frames2} → {out_cam2}")
    except Exception as e:
        print(f"[RawRec] Error: {e}")
    finally:
        if writer1 is not None: writer1.release()
        if writer2 is not None: writer2.release()
        with raw_record_lock:
            raw_record_state['active'] = False


@app.route('/record_10s')
def record_10s():
    # Fire-and-forget, avoid overlapping jobs
    with recording_lock:
        if not record_state['active']:
            threading.Thread(target=_record_current_view, kwargs={'duration_s': 10.0, 'target_fps': 30},
                             daemon=True).start()
            print("[Flask] Recording started (10s)")
        else:
            print("[Flask] Recording already in progress")
    return render_template_string(render_page())


@app.route('/record_raw_both_10s')
def record_raw_both_10s():
    with raw_record_lock:
        if not raw_record_state['active']:
            threading.Thread(target=_record_raw_both_10s,
                             kwargs={'duration_s': 10.0, 'target_fps': 30},
                             daemon=True).start()
            print("[Flask] RAW recording (cam1+cam2) started (10s)")
        else:
            print("[Flask] RAW recording already in progress")
    return render_template_string(render_page())


@app.route('/record_status')
def record_status():
    # existing display recorder
    with recording_lock:
        display = {
            'active': record_state['active'],
            'duration': record_state['duration'],
            'remaining': max(0.0, record_state['duration'] - (time.time() - record_state['t_start'])) if record_state[
                'active'] else 0.0,
            'filename': record_state['filename']
        }
    # new raw recorder
    with raw_record_lock:
        raw_active = raw_record_state['active']
        raw = {
            'active': raw_active,
            'duration': raw_record_state['duration'],
            'remaining': max(0.0, raw_record_state['duration'] - (
                        time.time() - raw_record_state['t_start'])) if raw_active else 0.0,
            'filenames': raw_record_state['filenames']
        }

    return jsonify({'display': display, 'raw': raw})


# ---------------- Setters exported for main.py ----------------
def update_cam1(data):
    with data_lock:
        cam1_data.update(data)

def update_cam2(data):
    with data_lock:
        cam2_data.update(data)

def update_fusion(data):
    with data_lock:
        fusion_data.update(data)

__all__ = ['app', 'update_cam1', 'update_cam2', 'update_fusion', 'current_mode']
