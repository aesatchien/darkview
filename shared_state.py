"""
shared_state.py  - 20250414 CJH

Defines all global configuration, queue declarations, and thread construction
for the dual-camera fusion vision system.

Responsibilities:
- Configures resolution, saturation threshold, and input sources
- Creates all necessary queues for data and preview flow
- Constructs camera threads (CameraWorker or SplitUC689Worker) and FusionWorker

Queue Architecture:
- cam1_data_queue, cam2_data_queue:
    → These carry frames for downstream processing (e.g., FusionWorker).
- cam1_view_queue, cam2_view_queue:
    → These carry frames for live preview display via Flask.
- fusion_queue:
    → Carries fused output frames for web streaming.

Worker Threads:
- cam1 and cam2 are instances of CameraWorker, unless using the UC-689 stereo camera.
- If USE_UC689 is True, a single SplitUC689Worker is used to split the frame
  into left (Cam1) and right (Cam2) views from a single physical device.
  It generates independent frame_data dicts and feeds them to the appropriate
  data and view queues for Cam1 and Cam2 respectively.

Fusion Thread:
- FusionWorker reads from the cam1_data_queue and cam2_data_queue only,
  synchronizes frames, performs fusion, and pushes to fusion_queue.

Test Mode:
- When USE_TEST_MODE is True, static and dynamic synthetic images are used
  for development and testing with no physical camera required.
"""

import queue
import cv2
import numpy as np
import time
import threading
from camera_thread_queue import CameraWorker, static_test_image, static_test_grid, dynamic_test_image, shutdown_requested
from fusion_worker import FusionWorker

# Configuration
# RESOLUTION = (1280, 720)
RESOLUTION = (640, 480)  # MS lifecams
SATURATION_THRESHOLD = 240
USE_TEST_MODE = False  # Use a fake image to test the functionality
USE_UC689 = False  # True means use UC-689 split mode - it's a stereo bar with two cams treated as one

if USE_TEST_MODE:
    cam1_source = static_test_grid
    cam2_source = dynamic_test_image
elif USE_UC689:
    cam1_source = "/dev/video0"
    cam2_source = None
else:  # need to make this smarter to query and use the two good cameras
    cam1_source = "/dev/video0"
    cam2_source = "/dev/video2"
print(f'cam sources are {cam1_source} and {cam2_source}')

# Queues
cam1_data_queue = queue.Queue(maxsize=1)
cam1_view_queue = queue.Queue(maxsize=1)
cam2_data_queue = queue.Queue(maxsize=1)
cam2_view_queue = queue.Queue(maxsize=1)
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

                self.cap.grab()
                ret, frame = self.cap.read()
                if not ret:
                    print(f"[{self.name}] Frame grab failed")
                    time.sleep(0.03)
                    continue

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame1, frame2 = split_uc689_frame(frame)

                for idx, (img, q_data, q_view, name, color) in enumerate([
                    (frame1, cam1_data_queue, cam1_view_queue, "Cam1", (255, 0, 0)),
                    (frame2, cam2_data_queue, cam2_view_queue, "Cam2", (0, 0, 255)),
                ]):
                    mask = self.compute_mask(img)
                    outlined, contours = self.draw_mask_outline(img, mask, color)
                    frame_data = {
                        'timestamp': time.time(),
                        'image': img,
                        'mask': mask,
                        'outlined': outlined,
                        'contours': contours
                    }
                    for q in [q_data, q_view]:
                        if q.full():
                            try:
                                q.get_nowait()
                            except queue.Empty:
                                pass
                        q.put(frame_data)
                    self.frame_counter += 1

                time.sleep(0.001)

    cam1 = SplitUC689Worker(
        name="UC689",
        device=cam1_source,
        overlay_color=(255, 255, 0),
        output_queue=None,
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
        output_queue=(cam1_data_queue, cam1_view_queue),
        test_mode=USE_TEST_MODE,
        test_image=cam1_source,
        resolution=RESOLUTION,
        saturation_threshold=SATURATION_THRESHOLD
    )

    cam2 = CameraWorker(
        name="Cam2",
        device=cam2_source,
        overlay_color=(0, 0, 255),  # Red
        output_queue=(cam2_data_queue, cam2_view_queue),
        test_mode=USE_TEST_MODE,
        test_image=cam2_source,
        resolution=RESOLUTION,
        saturation_threshold=SATURATION_THRESHOLD
    )

# Fusion thread
fusion = FusionWorker(
    cam1_queue=cam1_data_queue,
    cam2_queue=cam2_data_queue,
    fusion_queue=fusion_queue,
    cam1_overlay_color=(255, 0, 0),  # Blue
    cam2_overlay_color=(0, 0, 255),  # Red
    # 5, -18 seems to work for the arducam stereo bar (why should y be nonzero?)
    # 0, 10 seems to work on the stacked logitechs with cam2 on bottom
    # 18,-48 works on the stacked arducams when target is 2.5m away; 48,-49 is better when 1m away (y is ~ const?)
    overlap_trim_x=48,  #
    overlap_trim_y=-48,  #
)
