# DARKVIEW 
A Dual-Camera Fusion Vision System suitable for imaging solar events, welding and other high-brightness targets

This project implements a high-performance, multi-threaded image acquisition and fusion pipeline using two USB or Pi cameras on a Raspberry Pi. The system supports auto-exposure tuning, contour detection, and real-time visualization via a Flask-based web server. A fusion thread combines the two camera views into a synchronized composite stream, with masking and contour overlays.

Designed originally for use in robotics and real-time inspection, this version (V5) includes clean thread isolation, shared-state coordination, and test-mode support using synthetic images.

Some of the docs for the dual arducam are [general pi camera stuff](https://docs.arducam.com/Raspberry-Pi-Camera/Pivariety-Camera/Quick-Start-Guide/) and [exposure time](https://docs.arducam.com/UVC-Camera/Adjust-the-minimum-exposure-time/).

---

## Overview

- Camera Threads (`CameraWorker`) capture grayscale images, compute saturation masks, and generate outlined overlays.
- Fusion Thread synchronizes and combines the two camera streams, masking and drawing outlines for both views.
- Flask Web Server provides live viewing via `/stream`, and supports view switching and auto-exposure tuning.
- Shared State handles thread startup and communication, including test modes for development without hardware.
- Auto-Exposure Tuning adjusts camera settings dynamically to avoid overexposure based on mask coverage.

---

## File Descriptions

### camera_control.py
- Provides utility functions for setting v4l2 camera parameters
- Includes `auto_exposure_tune()` [experimental!] to scan and apply the best exposure based on mask saturation threshold

### camera_thread_queue.py
- Defines the `CameraWorker` thread class
- Captures grayscale frames from camera or test image
- Computes saturation mask and draws contours
- Pushes processed frames into an output queue (`maxsize=1`)
- Includes signal handler for clean `Ctrl+C` termination
- Also provides sample static/dynamic test image generators

### flask_server.py
- Hosts the web dashboard with view controls and a live MJPEG stream
- Endpoints:
  - `/` : main page with buttons to switch views and auto-tune cam2
  - `/stream` : MJPEG video stream (cam1, cam2, or fusion)
  - `/set_mode` : updates view mode
  - `/tune_cam2_exposure` : pauses cam2, tunes exposure, then resumes
- Uses `data_lock` and `update_cam1`, `update_cam2`, `update_fusion` for safe shared state updates

### fusion_worker.py
- Defines the `FusionWorker` thread class
- Synchronizes frames from cam1 and cam2 queues based on timestamp skew
- Trims non-overlapping regions, fuses images using mask from cam1
- Draws contours from both masks in colored overlays
- Re-pads fused image to full resolution for clean viewing

### main.py
- Launches all threads: cam1, cam2, fusion, and Flask feeder
- Registers SIGINT handler to stop all threads cleanly
- The Flask feeder thread continuously pulls the most recent frames and updates the web UI state
- Entry point for running the whole system

### shared_state.py
- Central config and thread construction
- Defines camera resolutions, saturation thresholds, and test mode sources
- Instantiates `CameraWorker` threads (cam1, cam2) and `FusionWorker`
- Defines `cam1_queue`, `cam2_queue`, and `fusion_queue` (all `Queue(maxsize=1)`)
- Allows switching between live camera and static test sources

---

## Getting Started

### Requirements
- Python 3.7+
- OpenCV (`cv2`)
- Flask
- NumPy
- v4l2 (Linux only, for auto-exposure)

### Run the System

    python3 main.py

Then open your browser to `http://<raspberry-pi-ip>:5000`

### Run in Test Mode
To try w/p a camera, `shared_state.py` can set `USE_TEST_MODE = True`. This uses synthetic images and allows rapid development with no hardware.

---

## Web Interface Controls (flask)

- **Switch Views**: Click `Cam1`, `Cam2`, or `Fusion` to switch output stream
- **Tune Exposure**: Click `Auto Tune Cam2 Exposure` to dynamically adjust cam2 exposure
- **Record Movie**: Click `Record` and a 10s video will be saved to the clips folder with a timestamp
---

## Notes

- Fusion logic assumes both images are grayscale and the same resolution
- Frame queues have `maxsize=1` to always store the latest frame
- Timestamp skew threshold in fusion is set to 50ms to avoid combining mismatched frames

---

