"""
fusion_worker.py  - 20250412 CJH

Defines the FusionWorker thread, which performs synchronized image fusion
using grayscale inputs from two cameras.

Responsibilities:
- Waits for timestamp-synced frames from cam1 and cam2 (via data queues)
- Trims overlapping edges in X and Y
- Applies mask-based pixel substitution from cam2 into cam1
- Draws contours from both masks in colored overlay
- Pads the final fused output to full width

Queue Flow:
- Input: cam1_data_queue, cam2_data_queue (must be timestamp-aligned)
- Output: fusion_queue, which contains dicts with:
    - 'fused': fused grayscale image
    - 'fused_with_outline': overlay with contours from both masks

Note on Contour Alignment:
- overlap_trim_x trims both cameras symmetrically in X; contours from both cams are shifted accordingly.
- overlap_trim_y is used to correct vertical misalignment between physical camera mounts (and sensor mount misalignment)
    - Only Cam2 is adjusted vertically to align with Cam1.
    - As a result, only Cam2's contours are shifted in Y when drawing on the fused image.
you can get the exact overlaps with a cv2.phaseCorrelate - at some point I should build this in

FusionWorker does not access the view queues and is not used for preview display.
"""


import threading
import time
import numpy as np
import queue
import cv2


class FusionWorker(threading.Thread):
    def __init__(self, cam1_queue, cam2_queue, fusion_queue, max_time_skew=0.25,
                 cam1_overlay_color=(255, 0, 0), cam2_overlay_color=(0, 0, 255),
                 overlap_trim_x=0, overlap_trim_y=-10):
        super().__init__(name="FusionWorker")
        self.cam1_queue = cam1_queue
        self.cam2_queue = cam2_queue
        self.fusion_queue = fusion_queue
        self.max_time_skew = max_time_skew
        self.cam1_overlay_color = cam1_overlay_color
        self.cam2_overlay_color = cam2_overlay_color
        self.overlap_trim_x = overlap_trim_x
        self.overlap_trim_y = overlap_trim_y
        self.use_clahe = True
        self.running = True
        self.frame_counter = 0

    def stop(self):
        self.running = False

    def crop_and_shift(self, img1, img2):
        x = self.overlap_trim_x
        y = self.overlap_trim_y

        img1_x = img1[:, x:]
        img2_x = img2[:, :-x or None]

        if y > 0:
            img1_cropped = img1_x[y:, :]
            img2_cropped = img2_x[:-y or None, :]
        elif y < 0:
            y = abs(y)
            img1_cropped = img1_x[:-y or None, :]
            img2_cropped = img2_x[y:, :]
        else:
            img1_cropped = img1_x
            img2_cropped = img2_x

        return img1_cropped, img2_cropped

    def fuse_images(self, img1, img2, mask1):
        fused = img1.copy()
        fused[mask1 > 0] = img2[mask1 > 0]
        return fused

    def draw_outlines_on_fused(self, fused, contours1, contours2):
        fused_color = cv2.cvtColor(fused, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(fused_color, contours1, -1, self.cam1_overlay_color, 1)
        # the contours need to be offset on cam2 since we are bringing it into registration with cam1

        cv2.drawContours(fused_color, contours2, -1, self.cam2_overlay_color, 1)
        return fused_color

    def pad_to_full_width(self, cropped_img):
        h, w = cropped_img.shape[:2]
        x = self.overlap_trim_x
        full_w = w + 2 * x
        if len(cropped_img.shape) == 2:
            padded = np.full((h, full_w), 128, dtype=np.uint8)
        else:
            padded = np.full((h, full_w, 3), 128, dtype=np.uint8)
        padded[:, x:x + w] = cropped_img
        return padded

    def shift_contours(self, contours, dx=0, dy=0):
        shifted = []
        for cnt in contours:
            cnt_shifted = cnt + np.array([[[dx, dy]]], dtype=cnt.dtype)
            shifted.append(cnt_shifted)
        return shifted

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

            # allow for overlap mismatch in both x and y for the two cameras
            img1, img2 = self.crop_and_shift(frame1['image'], frame2['image'])
            mask1, mask2 = self.crop_and_shift(frame1['mask'], frame2['mask'])
            x = self.overlap_trim_x
            y = self.overlap_trim_y

            # Cam1: only shift X
            contours1 = self.shift_contours(frame1['contours'], dx=-x, dy=0)
            # Cam2: only shift Y?  When I first wrote this I have cams stacked horizontally, then vertically
            contours2 = self.shift_contours(frame2['contours'], dx=0, dy=+y)

            # Optional CLAHE enhancement on the filtered image to undarken
            if self.use_clahe:
                img1 = apply_clahe_masked_region(img1, np.ones_like(img1) - mask1, clip_limit=1)
                img2 = apply_clahe_masked_region(img2, mask1)

            fused = self.fuse_images(img1, img2, mask1)
            fused_with_outline = self.draw_outlines_on_fused(fused, contours1, contours2)

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
            self.frame_counter += 1

            time.sleep(0.001)


def apply_clahe_masked_region(image, mask, clip_limit=4.0, tile_grid_size=(8, 8)):
    """
    Efficient CLAHE contrast enhancement only on masked region (grayscale or BGR).
    Applies CLAHE only to the bounding box surrounding nonzero mask pixels.
    Returns a copy of the image with enhanced region.
    4 is about as high as you want to go with clip limit before it starts enhancing noise
    """
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        return image  # nothing to do

    x_min, x_max = xs.min(), xs.max()
    y_min, y_max = ys.min(), ys.max()

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)

    roi_img = image[y_min:y_max+1, x_min:x_max+1]
    roi_mask = mask[y_min:y_max+1, x_min:x_max+1]

    if len(roi_img.shape) == 2 or roi_img.shape[2] == 1:  # Grayscale
        l = roi_img  #  no need to copy this .copy()
        l_clahe = l.copy()
        l_clahe[roi_mask > 0] = clahe.apply(l)[roi_mask > 0]
        output = image.copy()
        output[y_min:y_max+1, x_min:x_max+1] = l_clahe
        return output

    elif len(roi_img.shape) == 3 and roi_img.shape[2] == 3:  # BGR
        lab = cv2.cvtColor(roi_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_clahe = l.copy()
        l_full = clahe.apply(l)
        l_clahe[roi_mask > 0] = l_full[roi_mask > 0]
        merged = cv2.merge((l_clahe, a, b))
        roi_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        output = image.copy()
        output[y_min:y_max+1, x_min:x_max+1] = roi_bgr
        return output

    else:
        raise ValueError("Unsupported image format for CLAHE")
