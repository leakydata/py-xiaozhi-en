#!/usr/bin/env python3
"""Find the available cameras (OpenCV/V4L2, plus picamera2 when present) and optionally write the choice back to the CAMERA config."""

import argparse
import logging
import sys
from pathlib import Path

# put the project root on the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config_manager import initialize_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("CameraScanner")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan for cameras, and optionally save one to the config"
    )
    parser.add_argument(
        "--select",
        type=int,
        default=None,
        help="save the camera at this position in the list (counting from 0) to the config",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "opencv", "picamera2"],
        default=None,
        help="write CAMERA.backend explicitly",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="write CAMERA.device explicitly (e.g. /dev/video0)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="take a test frame using the current config, or whatever --select chose",
    )
    args = parser.parse_args()

    config = initialize_config()
    from src.mcp.tools.camera.capture_backend import (
        CaptureConfig,
        apply_device_selection,
        capture_jpeg,
        list_camera_devices,
        load_capture_config,
    )

    current = load_capture_config()
    print("\n===== current CAMERA config =====")
    print(f"  backend={current.backend}")
    print(f"  device={current.device!r}")
    print(f"  camera_index={current.camera_index}")
    print(f"  size={current.frame_width}x{current.frame_height}")
    print(f"  warm_up_frames={current.warm_up_frames}")

    print("\n===== scanning =====\n")
    devices = list_camera_devices()
    if not devices:
        print("No cameras found.")
        print("Things to check:")
        print("  - USB: make sure it is plugged in, and check ls /dev/video*")
        print("  - Raspberry Pi CSI: sudo apt install python3-picamera2")
        print(
            "  - your user needs to be in the video group: sudo usermod -aG video $USER && newgrp video"
        )
        return 1

    for i, d in enumerate(devices):
        print(f"  [{i}] {d.name}  key={d.key}  kind={d.kind}")

    selected_key = None
    if args.device:
        selected_key = args.device
    elif args.backend == "picamera2":
        selected_key = "picamera2"
    elif args.select is not None:
        if args.select < 0 or args.select >= len(devices):
            print(f"--select is out of range; it must be 0..{len(devices) - 1}")
            return 1
        selected_key = devices[args.select].key

    if selected_key is not None:
        updates = apply_device_selection(selected_key)
        if args.backend:
            updates["CAMERA.backend"] = args.backend
        for path, value in updates.items():
            config.update_config(path, value)
        print("\nSaved to the config:")
        for path, value in updates.items():
            print(f"  {path} = {value!r}")

    if args.test or selected_key is not None:
        print("\n===== test capture =====")
        cfg = load_capture_config()
        if selected_key is not None:
            # use whatever --select just wrote
            u = apply_device_selection(selected_key)
            if args.backend:
                u["CAMERA.backend"] = args.backend
            cfg = CaptureConfig(
                camera_index=int(u.get("CAMERA.camera_index", 0) or 0),
                device=str(u.get("CAMERA.device", "") or ""),
                backend=str(u.get("CAMERA.backend", "auto")),
                frame_width=cfg.frame_width,
                frame_height=cfg.frame_height,
                warm_up_frames=cfg.warm_up_frames,
            )
        jpeg = capture_jpeg(cfg)
        if not jpeg:
            print("The test capture failed")
            return 2
        out = project_root / "camera_scan_test.jpg"
        out.write_bytes(jpeg)
        print(f"Test capture saved: {out} ({len(jpeg)} bytes)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
