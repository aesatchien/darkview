"""
camera_thread_queue.  - 20250412 CJH

Defines the CameraWorker class for threaded image acquisition and processing.
Each CameraWorker captures grayscale frames, computes saturation masks, and overlays
contour outlines. Supports test image sources for development without hardware.

Globals:
- shutdown_requested: Shared Event used to gracefully terminate threads.
- signal_handler (if used as main): Catches SIGINT and exits cleanly.

Classes:
- CameraWorker: Threaded camera capture worker.
Functions:
- static_test_image, static_test_grid, dynamic_test_image: Synthetic test image generators.
"""

import cv2
import threading
import time
import numpy as np
import queue

shutdown_requested = threading.Event()


class CameraWorker(threading.Thread):
    def __init__(self, name, device, overlay_color, output_queue, test_mode=False, test_image=None,
                 resolution=(1280, 720), saturation_threshold=250):
        super().__init__(name=name)
        self.name = name
        self.device = device
        self.overlay_color = overlay_color
        self.output_queue = output_queue
        self.test_mode = test_mode
        self.test_image = test_image
        self.resolution = resolution
        self.saturation_threshold = saturation_threshold
        self.running = True
        self.pause_capture = threading.Event()

        if not self.test_mode:
            self.cap = cv2.VideoCapture(self.device)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    def stop(self):
        self.running = False
        if not self.test_mode:
            self.cap.release()

    def compute_mask(self, image):
        return cv2.inRange(image, self.saturation_threshold, 255)

    def draw_mask_outline(self, image, mask):
        outlined = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(outlined, contours, -1, self.overlay_color, 2)
        return outlined

    def run(self):
        while self.running and not shutdown_requested.is_set():
            if self.pause_capture.is_set():
                time.sleep(0.01)
                continue

            if self.test_mode:
                frame = self.test_image() if callable(self.test_image) else self.test_image.copy()
            else:
                ret, frame = self.cap.read()
                if not ret:
                    print(f"[{self.name}] Frame grab failed")
                    time.sleep(0.05)
                    continue
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            mask = self.compute_mask(frame)
            outlined = self.draw_mask_outline(frame, mask)

            frame_data = {
                'timestamp': time.time(),
                'image': frame,
                'mask': mask,
                'outlined': outlined
            }

            # Only push if consumer has cleared the slot - limit the camera FPS
            try:
                self.output_queue.put(frame_data, timeout=0.01)
            except queue.Full:
                time.sleep(0.005)  # Back off briefly if not consumed

            # this is balls-out, no limit on the cam1 and cam2 queues
            # if self.output_queue.full():
            #     try:
            #         self.output_queue.get_nowait()
            #     except queue.Empty:
            #         pass
            # self.output_queue.put(frame_data)
            time.sleep(0.001)

# Example static test image
def static_test_image():
    img = np.zeros((720, 1280), dtype=np.uint8)
    cv2.rectangle(img, (300, 300), (1000, 500), 255, -1)
    return img

def static_test_grid():
    height, width = 720, 1280
    tile_size = 64
    gap = 10
    white_size = tile_size - gap

    rows = height // tile_size
    cols = width // tile_size

    img = np.full((height, width), 64, dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                y0 = r * tile_size + gap // 2
                x0 = c * tile_size + gap // 2
                y1 = y0 + white_size
                x1 = x0 + white_size
                # Clamp to image size to prevent overrun
                y1 = min(y1, height)
                x1 = min(x1, width)
                img[y0:y1, x0:x1] = 255
    return img


# Example dynamic test image
def dynamic_test_image():
    t = int(time.time() * 90) % 1280
    img = np.zeros((720, 1280), dtype=np.uint8)
    cv2.rectangle(img, (t, 300), (t + 100, 500), 128, -1)
    cv2.rectangle(img, (t+100, 300), (t + 200, 500), 255, -1)
    return img
