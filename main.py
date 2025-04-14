import threading
import time
import signal
import sys
import queue
from shared_state import cam1, cam2, fusion, cam1_queue, cam2_queue, fusion_queue
from camera_thread_queue import shutdown_requested
from flask_server import app, update_cam1, update_cam2, update_fusion, current_mode


# Flask feeder thread
def flask_feeder():
    while not shutdown_requested.is_set():
        try:
            view = current_mode['view']
            if view == 'cam1':
                try:
                    frame = cam1_queue.get(timeout=1.0)
                    update_cam1(frame)
                except queue.Empty:
                    pass
            elif view == 'cam2':
                try:
                    frame = cam2_queue.get(timeout=1.0)
                    update_cam2(frame)
                except queue.Empty:
                    pass
            elif view == 'fusion':
                try:
                    frame = fusion_queue.get(timeout=1.0)
                    update_fusion(frame)
                except queue.Empty:
                    pass
        except Exception as e:
            print(f"[Feeder] Error: {e}")
        time.sleep(0.001)


# Graceful shutdown

def shutdown_handler(signum, frame):
    print("\n[Main] Caught SIGINT, shutting down threads and Flask...")
    shutdown_requested.set()
    print("[Main] stopping cams...")
    if cam1:
        cam1.stop()
    if cam2:
        cam2.stop()
    print("[Main] stopping fusion...")
    fusion.stop()
    print("[Main] joining cams...")
    if cam1:
        cam1.join()
    if cam2:
        cam2.join()
    fusion.join()
    print("[Main] sysexit!")
    sys.exit(0)

def monitor_fps():
    last_ts_c1 = last_ts_c2 = last_ts_f = 0
    count_c1 = count_c2 = count_f = 0
    prev_time = time.time()
    last_count_c1 = 0
    last_count_c2 = 0
    last_count_f = 0

    while True:
        # if not cam1_queue.empty():
        #     ts = cam1_queue.queue[0]['timestamp']
        #     if ts != last_ts_c1:
        #         count_c1 += 1
        #         last_ts_c1 = ts
        # if not cam2_queue.empty():
        #     ts = cam2_queue.queue[0]['timestamp']
        #     if ts != last_ts_c2:
        #         count_c2 += 1
        #         last_ts_c2 = ts
        # if not fusion_queue.empty():
        #     ts = fusion_queue.queue[0]['timestamp']
        #     if ts != last_ts_f:
        #         count_f += 1
        #         last_ts_f = ts

        now = time.time()
        if now - prev_time >= 1.0:
            count_c1 = cam1.frame_counter - last_count_c1
            count_c2 = cam2.frame_counter - last_count_c2 if cam2 else 0
            count_f = fusion.frame_counter - last_count_f  # already exists

            last_count_c1 = cam1.frame_counter
            last_count_c2 = cam2.frame_counter if cam2 else 0
            last_count_f = fusion.frame_counter

            print(f"Cam1: {count_c1:03d} FPS  Cam2: {count_c2:03d} FPS  Fusion: {count_f:03d} FPS", end="\r")

            prev_time = now

        time.sleep(0.001)  # 1000 Hz monitor to avoid missing fast updates


signal.signal(signal.SIGINT, shutdown_handler)

# Start threads
if cam1:
    cam1.start()
if cam2:
    cam2.start()
fusion.start()
threading.Thread(target=monitor_fps, daemon=True).start()
threading.Thread(target=flask_feeder, daemon=True).start()

# Launch Flask
if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        shutdown_handler(None, None)
