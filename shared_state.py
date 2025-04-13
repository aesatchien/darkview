"""
shared_state.py  - 20250412 CJH

Central configuration and thread construction for the camera fusion system.
Creates queues, test sources, and CameraWorker and FusionWorker threads.

Globals:
- cam1, cam2: CameraWorker instances for cam1 and cam2.
- fusion: FusionWorker instance.
- cam1_queue, cam2_queue, fusion_queue: Single-frame queues for each stage of the pipeline.

Supports test mode via USE_TEST_MODE to substitute synthetic images for hardware capture.
"""

import queue
from camera_thread_queue import CameraWorker, static_test_image, static_test_grid, dynamic_test_image
from fusion_worker import FusionWorker

# Configuration
RESOLUTION = (1280, 720)
SATURATION_THRESHOLD = 250
USE_TEST_MODE = True

if USE_TEST_MODE:
    cam1_source = static_test_grid
    cam2_source = dynamic_test_image
else:
    cam1_source = "/dev/video0"
    cam2_source = "/dev/video1"

# Queues
cam1_queue = queue.Queue(maxsize=1)
cam2_queue = queue.Queue(maxsize=1)
fusion_queue = queue.Queue(maxsize=1)

# Camera threads
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
