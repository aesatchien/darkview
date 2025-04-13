"""
main.py  - 20250412 CJH

Primary entry point for launching the camera fusion server system.
Starts cam1, cam2, and fusion threads, and runs the Flask app for live web streaming.

Features:
- Registers a SIGINT handler for graceful shutdown.
- Launches a feeder thread that updates Flask’s shared frame state.
- Starts Flask server on 0.0.0.0:5000 for network access.

Imports shared components from shared_state and flask_server.
"""

import threading
import time
import signal
import sys
from shared_state import cam1, cam2, fusion, cam1_queue, cam2_queue, fusion_queue
from camera_thread_queue import shutdown_requested
from flask_server import app, update_cam1, update_cam2, update_fusion


# Flask feeder thread
def flask_feeder():
    while not shutdown_requested.is_set():
        try:
            if not cam1_queue.empty():
                update_cam1(cam1_queue.queue[0])
            if not cam2_queue.empty():
                update_cam2(cam2_queue.queue[0])
            if not fusion_queue.empty():
                update_fusion(fusion_queue.queue[0])
        except Exception as e:
            print(f"[Feeder] Error: {e}")
        time.sleep(0.01)


# Graceful shutdown
def shutdown_handler(signum, frame):
    print("\n[Main] Caught SIGINT, shutting down threads and Flask...")
    shutdown_requested.set()
    cam1.stop()
    cam2.stop()
    fusion.stop()
    cam1.join()
    cam2.join()
    fusion.join()
    sys.exit(0)


def monitor_fps():
    last_ts_c1 = last_ts_c2 = last_ts_f = 0
    count_c1 = count_c2 = count_f = 0
    prev_time = time.time()

    while True:
        if not cam1_queue.empty():
            ts = cam1_queue.queue[0]['timestamp']
            if ts != last_ts_c1:
                count_c1 += 1
                last_ts_c1 = ts
        if not cam2_queue.empty():
            ts = cam2_queue.queue[0]['timestamp']
            if ts != last_ts_c2:
                count_c2 += 1
                last_ts_c2 = ts
        if not fusion_queue.empty():
            ts = fusion_queue.queue[0]['timestamp']
            if ts != last_ts_f:
                count_f += 1
                last_ts_f = ts

        now = time.time()
        if now - prev_time >= 1.0:
            print(f"Cam1: {count_c1:03d} FPS  Cam2: {count_c2:03d} FPS  Fusion: {count_f:03d} FPS", end="\r")
            count_c1 = count_c2 = count_f = 0
            prev_time = now

        time.sleep(0.001)  # 1000 Hz monitor to avoid missing fast updates

# Trap CTRL-C so we can close cleanly
signal.signal(signal.SIGINT, shutdown_handler)

# Start threads
cam1.start()
cam2.start()
fusion.start()
threading.Thread(target=monitor_fps, daemon=True).start()
threading.Thread(target=flask_feeder, daemon=True).start()

# Launch Flask - you do all the interactions via the web interface
if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        shutdown_handler(None, None)
