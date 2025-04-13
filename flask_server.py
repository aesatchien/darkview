"""
flask_server.py  - 20250412 CJH

Flask-based web server for live viewing of camera and fusion output.
Provides buttons for switching view modes and triggering cam2 exposure tuning.

Endpoints:
- '/'                : HTML page with view and tuning controls.
- '/stream'          : MJPEG video stream of cam1, cam2, or fusion.
- '/set_mode'        : Switches active view mode (cam1, cam2, fusion).
- '/tune_cam2_exposure': Temporarily pauses cam2 and runs exposure tuning.

Functions:
- update_cam1, update_cam2, update_fusion: Thread-safe setters for updating shared image dictionaries.
Globals:
- cam1_data, cam2_data, fusion_data: Shared frame dictionaries accessed by the stream handler.
- data_lock: Ensures atomic access to shared data across threads.
"""

from flask import Flask, Response, render_template_string, request
import threading
import time
import cv2
from camera_control import auto_exposure_tune
from shared_state import cam2, cam2_queue

app = Flask(__name__)

# Shared state
cam1_data = {}
cam2_data = {}
fusion_data = {}
data_lock = threading.Lock()

# Mode can be 'cam1', 'cam2', 'fusion'
current_mode = {'view': 'cam1'}

# HTML Template
HTML_PAGE = """
<!doctype html>
<html>
<head>
  <title>Camera Fusion Viewer</title>
</head>
<body>
  <h2>Live Stream</h2>
  <form method="get" action="/set_mode">
    <button name="view" value="cam1">Cam1 (Blue Outline)</button>
    <button name="view" value="cam2">Cam2 (Red Outline)</button>
    <button name="view" value="fusion">Fusion</button>
  </form>
  <form method="get" action="/tune_cam2_exposure">
    <button type="submit">Auto Tune Cam2 Exposure</button>
  </form>
  <img src="/stream" width="1280" height="720">
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/set_mode')
def set_mode():
    view = request.args.get('view', 'cam1')
    if view in ['cam1', 'cam2', 'fusion']:
        current_mode['view'] = view
        print(f"[Flask] Switched to view: {view}")
    return render_template_string(HTML_PAGE)

@app.route('/tune_cam2_exposure')
def tune_cam2_exposure():
    cam2.pause_capture.set()
    auto_exposure_tune("/dev/video1", cam2_queue)
    cam2.pause_capture.clear()
    return render_template_string(HTML_PAGE)

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
            time.sleep(0.03)  # ~30 FPS cap

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

# These setters should be called by the camera and fusion threads
def update_cam1(data):
    with data_lock:
        cam1_data.update(data)

def update_cam2(data):
    with data_lock:
        cam2_data.update(data)

def update_fusion(data):
    with data_lock:
        fusion_data.update(data)

# Export update functions for main.py to call
__all__ = ['app', 'update_cam1', 'update_cam2', 'update_fusion']
