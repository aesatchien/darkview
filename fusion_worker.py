"""
fusion_worker.py  - 20250412 CJH

Defines the FusionWorker class, which fuses synchronized frames from cam1 and cam2.
It trims overlap, applies mask-based pixel replacement, draws outlines from both masks,
and pads the result to full resolution.

Class:
- FusionWorker: Thread that waits for time-synced cam1/cam2 frames, performs fusion,
  and pushes results into a queue for web display or further use.
"""

import threading
import time
import numpy as np
import queue
import cv2

class FusionWorker(threading.Thread):
    def __init__(self, cam1_queue, cam2_queue, fusion_queue, max_time_skew=0.05,
                 cam1_overlay_color=(255, 0, 0), cam2_overlay_color=(0, 0, 255),
                 overlap_trim_x=80):
        super().__init__(name="FusionWorker")
        self.cam1_queue = cam1_queue
        self.cam2_queue = cam2_queue
        self.fusion_queue = fusion_queue
        self.max_time_skew = max_time_skew
        self.cam1_overlay_color = cam1_overlay_color
        self.cam2_overlay_color = cam2_overlay_color
        self.overlap_trim_x = overlap_trim_x
        self.running = True

    def stop(self):
        self.running = False

    def crop_and_shift(self, img1, img2):
        x = self.overlap_trim_x
        img1_cropped = img1[:, x:]      # trim left edge of cam1
        img2_cropped = img2[:, :-x]     # trim right edge of cam2
        return img1_cropped, img2_cropped

    def fuse_images(self, img1, img2, mask1):
        fused = img1.copy()
        fused[mask1 > 0] = img2[mask1 > 0]
        return fused

    def draw_outlines_on_fused(self, fused, mask1, mask2):
        fused_color = cv2.cvtColor(fused, cv2.COLOR_GRAY2BGR)
        contours1, _ = cv2.findContours(mask1, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours2, _ = cv2.findContours(mask2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(fused_color, contours1, -1, self.cam1_overlay_color, 1)
        cv2.drawContours(fused_color, contours2, -1, self.cam2_overlay_color, 1)
        return fused_color

    def pad_to_full_width(self, cropped_img):
        h, w = cropped_img.shape[:2]
        x = self.overlap_trim_x
        full_w = w + 2 * x  # pad both sides
        if len(cropped_img.shape) == 2:
            padded = np.full((h, full_w), 128, dtype=np.uint8)
        else:
            padded = np.full((h, full_w, 3), 128, dtype=np.uint8)
        padded[:, x:x + w] = cropped_img
        return padded

    def run(self):
        while self.running:
            try:
                frame1 = self.cam1_queue.get(timeout=1.0)
                frame2 = self.cam2_queue.get(timeout=1.0)
            except queue.Empty:
                print("[FusionWorker] Timeout waiting for camera frames")
                continue

            ts1 = frame1['timestamp']
            ts2 = frame2['timestamp']
            if abs(ts1 - ts2) > self.max_time_skew:
                print(f"[FusionWorker] Timestamp skew too large: |{ts1 - ts2:.3f}s| — skipping frame")
                continue

            img1, img2 = self.crop_and_shift(frame1['image'], frame2['image'])
            mask1, mask2 = self.crop_and_shift(frame1['mask'], frame2['mask'])

            fused = self.fuse_images(img1, img2, mask1)
            fused_with_outline = self.draw_outlines_on_fused(fused, mask1, mask2)

            padded_fused = self.pad_to_full_width(fused)
            padded_fused_with_outline = self.pad_to_full_width(fused_with_outline)

            fused_data = {
                'timestamp': time.time(),
                'fused': padded_fused,
                'fused_with_outline': padded_fused_with_outline
            }

            if self.fusion_queue.full():
                try:
                    self.fusion_queue.get_nowait()
                except queue.Empty:
                    pass
            self.fusion_queue.put(fused_data)

            time.sleep(0.001)
