import subprocess
import numpy as np
import time
import queue


def set_camera_param(device, param, value):
    try:
        subprocess.run(
            ["v4l2-ctl", "-d", device, f"--set-ctrl={param}={value}"],
            check=True
        )
        print(f"[CameraControl] Set {param} to {value} on {device}")
    except subprocess.CalledProcessError as e:
        print(f"[CameraControl] Failed to set {param} on {device}: {e}")


def auto_exposure_tune(cam_device, cam_queue, target_pct=1.5, exposure_list=None):
    if exposure_list is None:
        exposure_list = [16000, 8000, 4000, 2000, 1000, 500]

    print(f"\n[AutoExposure] Starting sweep on {cam_device}")
    best_exposure = None

    for exposure in exposure_list:
        set_camera_param(cam_device, "exposure_absolute", exposure)
        time.sleep(0.1)  # let setting take effect

        try:
            frame_data = cam_queue.get(timeout=1.0)
        except queue.Empty:
            print(f"[AutoExposure] Timeout at exposure {exposure}")
            continue

        mask = frame_data['mask']
        saturation_pct = 100.0 * np.count_nonzero(mask) / mask.size
        print(f"Exposure {exposure:5d} µs → Saturation: {saturation_pct:.2f}%")

        if saturation_pct <= target_pct:
            best_exposure = exposure
            break

    if best_exposure:
        print(f"[AutoExposure] Selected exposure: {best_exposure} \n")
        set_camera_param(cam_device, "exposure_absolute", best_exposure)
    else:
        print("[AutoExposure] No exposure found below target saturation threshold")
