import queue
import cv2
import numpy as np
import time
import threading
from camera_thread_queue import CameraWorker, static_test_image, static_test_grid, dynamic_test_image, shutdown_requested
from fusion_worker import FusionWorker

# Configuration
RESOLUTION = (1280, 720)
SATURATION_THRESHOLD = 250
USE_TEST_MODE = False
USE_UC689 = True  # True means use UC-689 split mode - it's a stereo bar with two cams treated as one

if USE_TEST_MODE:
    cam1_source = static_test_grid
    cam2_source = dynamic_test_image
elif USE_UC689:
    cam1_source = "/dev/video0"
    cam2_source = None
else:
    cam1_source = "/dev/video0"
    cam2_source = "/dev/video1"

# Queues
cam1_queue = queue.Queue(maxsize=1)
cam2_queue = queue.Queue(maxsize=1)
fusion_queue = queue.Queue(maxsize=1)

def split_uc689_frame(frame):
    left = frame[:, :1280]
    right = frame[:, 1280:]
    return left, right

if USE_UC689:
    class SplitUC689Worker(CameraWorker):
        def run(self):
            while self.running and not shutdown_requested.is_set():
                if self.pause_capture.is_set():
                    time.sleep(0.01)
                    continue

                ret, frame = self.cap.read()
                if not ret:
                    print(f"[{self.name}] Frame grab failed")
                    time.sleep(0.05)
                    continue

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame1, frame2 = split_uc689_frame(frame)

                for idx, (img, q, name, color) in enumerate([
                    (frame1, cam1_queue, "Cam1", (255, 0, 0)),
                    (frame2, cam2_queue, "Cam2", (0, 0, 255)),
                ]):
                    mask = self.compute_mask(img)
                    outlined = self.draw_mask_outline(img, mask)
                    frame_data = {
                        'timestamp': time.time(),
                        'image': img,
                        'mask': mask,
                        'outlined': outlined
                    }
                    try:
                        q.put(frame_data, timeout=0.01)
                    except queue.Full:
                        time.sleep(0.005)

                time.sleep(0.001)

    cam1 = SplitUC689Worker(
        name="UC689",
        device=cam1_source,
        overlay_color=(255, 255, 0),
        output_queue=None,
        test_mode=False,
        test_image=None,
        resolution=(2560, 720),
        saturation_threshold=SATURATION_THRESHOLD
    )
    cam2 = None  # virtual only
else:
    cam1 = CameraWorker(
        name="Cam1",
        device=cam1_source,
        overlay_color=(255, 0, 0),  # Blue
        output_queue=cam1_queue,
        test_mode=USE_TEST_MODE,
        test_image=cam1_source,
        resolution=RESOLUTION,
        saturation_threshold=SATURATION_THRESHOLD
    )

    cam2 = CameraWorker(
        name="Cam2",
        device=cam2_source,
        overlay_color=(0, 0, 255),  # Red
        output_queue=cam2_queue,
        test_mode=USE_TEST_MODE,
        test_image=cam2_source,
        resolution=RESOLUTION,
        saturation_threshold=SATURATION_THRESHOLD
    )

# Fusion thread
fusion = FusionWorker(
    cam1_queue=cam1_queue,
    cam2_queue=cam2_queue,
    fusion_queue=fusion_queue,
    cam1_overlay_color=(255, 0, 0),  # Blue
    cam2_overlay_color=(0, 0, 255),  # Red
    overlap_trim_x=80
)
