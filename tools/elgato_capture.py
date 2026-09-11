#!/usr/bin/env python3
"""
Elgato / Game Capture device enumeration for Swipe Lab (Tools lock).

Uses OpenCV as a webcam (DirectShow on Windows, V4L2 on Linux).
Does NOT require the Elgato SDK. Prefer pin-by-name/VID — never assume index 0.

Import path for swipe_ui:
  from elgato_capture import list_devices, find_elgato, open_capture, pin_elgato
"""

from __future__ import annotations

import re
import sys
from typing import Any

# Name substrings that identify Elgato / Game Capture devices (case-insensitive)
ELGATO_NAME_PATTERNS: tuple[str, ...] = (
    "elgato",
    "game capture",
    "4k60",
    "4k capture",
    "hd60",
    "hd60s",
    "hd60 x",
    "hd60 pro",
    "4kce",
)

# Known Elgato USB VID (hex string without 0x) — used when platform exposes it
ELGATO_VID = "0fd9"

# Sensible preview defaults for lab scoring
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 60

_CV2 = None
_CV2_ERR: str | None = None


def _cv2():
    """Lazy import OpenCV; returns module or None."""
    global _CV2, _CV2_ERR
    if _CV2 is not None:
        return _CV2
    if _CV2_ERR is not None:
        return None
    try:
        import cv2 as _cv

        _CV2 = _cv
        return _CV2
    except Exception as exc:  # noqa: BLE001 — optional dep
        _CV2_ERR = str(exc)
        return None


def opencv_available() -> bool:
    return _cv2() is not None


def opencv_error() -> str | None:
    _cv2()
    return _CV2_ERR


def _backend_flag() -> int | None:
    """Platform capture backend preference."""
    cv2 = _cv2()
    if cv2 is None:
        return None
    if sys.platform.startswith("win"):
        return getattr(cv2, "CAP_DSHOW", None)
    if sys.platform.startswith("linux"):
        return getattr(cv2, "CAP_V4L2", None)
    return None


def _name_looks_elgato(name: str) -> bool:
    n = (name or "").lower()
    return any(p in n for p in ELGATO_NAME_PATTERNS)


def _vid_looks_elgato(vid: str | None) -> bool:
    if not vid:
        return False
    return vid.lower().replace("0x", "") == ELGATO_VID


def list_devices(max_index: int = 10) -> list[dict[str, Any]]:
    """
    Enumerate OpenCV video devices.

    Returns list of {index, name, backend, is_elgato, vid?}.
    Graceful empty list if OpenCV missing or no devices.
    """
    cv2 = _cv2()
    if cv2 is None:
        return []

    backend = _backend_flag()
    found: list[dict[str, Any]] = []

    # Try to get friendly names on Windows via DirectShow property if available
    for idx in range(max_index):
        cap = None
        try:
            if backend is not None:
                cap = cv2.VideoCapture(idx, backend)
            else:
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                continue
            name = _probe_name(cv2, cap, idx)
            entry: dict[str, Any] = {
                "index": idx,
                "name": name,
                "backend": _backend_label(backend),
                "is_elgato": _name_looks_elgato(name),
            }
            found.append(entry)
        except Exception:  # noqa: BLE001
            continue
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass

    # Prefer Elgato-named devices sorted first for UI cycling
    found.sort(key=lambda d: (0 if d["is_elgato"] else 1, d["index"]))
    return found


def _backend_label(backend: int | None) -> str:
    if backend is None:
        return "default"
    cv2 = _cv2()
    if cv2 is None:
        return "default"
    if backend == getattr(cv2, "CAP_DSHOW", -1):
        return "dshow"
    if backend == getattr(cv2, "CAP_V4L2", -1):
        return "v4l2"
    return str(backend)


def _probe_name(cv2: Any, cap: Any, idx: int) -> str:
    """Best-effort device name; falls back to VideoN."""
    # CAP_PROP_BACKEND / custom — OpenCV rarely exposes USB product string.
    # On Linux, try /sys or /dev/v4l/by-id via side channel.
    if sys.platform.startswith("linux"):
        linux_name = _linux_v4l_name(idx)
        if linux_name:
            return linux_name
    # Windows: CAP_PROP is limited; leave generic unless CAP_PROP_SETTINGS
    backend_name = ""
    try:
        # Some builds expose device path via CAP_PROP_GUID-ish — not portable.
        pass
    except Exception:  # noqa: BLE001
        pass
    return backend_name or f"Video{idx}"


def _linux_v4l_name(index: int) -> str | None:
    """Read V4L2 card name from sysfs if present."""
    import os

    # Map /dev/videoN → name
    path = f"/sys/class/video4linux/video{index}/name"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        # Also try by-id symlink scan
        by_id = "/dev/v4l/by-id"
        if not os.path.isdir(by_id):
            return None
        target = f"video{index}"
        for name in os.listdir(by_id):
            try:
                link = os.readlink(os.path.join(by_id, name))
            except OSError:
                continue
            if link.rstrip("/").endswith(target) or target in link:
                # by-id names often include usb-Elgato_...
                return name.replace("-video-index0", "").replace("_", " ")
        return None


def find_elgato(devices: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Return preferred Elgato device dict, or None."""
    devs = devices if devices is not None else list_devices()
    for d in devs:
        if d.get("is_elgato"):
            return d
    # Fallback: name match against patterns even if flag missed
    for d in devs:
        if _name_looks_elgato(str(d.get("name", ""))):
            return d
    return None


def pin_elgato(
    index_or_name: int | str | None = None,
    *,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Resolve and pin a capture device.

    - None → prefer Elgato by name; else None (do NOT silently pick index 0)
    - int → that index (still records name)
    - str → match substring against device names (case-insensitive)
    """
    devs = devices if devices is not None else list_devices()
    if index_or_name is None:
        return find_elgato(devs)

    if isinstance(index_or_name, int):
        for d in devs:
            if d["index"] == index_or_name:
                return d
        # Device may open even if enum missed it
        return {
            "index": index_or_name,
            "name": f"Video{index_or_name}",
            "backend": _backend_label(_backend_flag()),
            "is_elgato": False,
            "pinned_unverified": True,
        }

    needle = str(index_or_name).strip().lower()
    # Numeric string?
    if re.fullmatch(r"\d+", needle):
        return pin_elgato(int(needle), devices=devs)

    for d in devs:
        if needle in str(d.get("name", "")).lower():
            return d
    return None


def open_capture(
    index_or_name: int | str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> tuple[Any | None, dict[str, Any]]:
    """
    Open a cv2.VideoCapture with sensible defaults.

    Returns (cap_or_None, info_dict).
    info always includes: ok, reason?, device?, width, height, fps, opencv_available.
    Graceful: if OpenCV missing or no device, cap is None and UI can still run objective.
    """
    info: dict[str, Any] = {
        "ok": False,
        "opencv_available": opencv_available(),
        "width": width,
        "height": height,
        "fps": fps,
        "device": None,
        "reason": None,
    }
    cv2 = _cv2()
    if cv2 is None:
        info["reason"] = f"opencv_missing: {_CV2_ERR or 'import failed'}"
        return None, info

    pinned = pin_elgato(index_or_name)
    if pinned is None:
        info["reason"] = (
            "no_elgato_pinned: enumerate devices and pass --capture "
            "name/index; refusing silent index-0"
        )
        info["devices"] = list_devices()
        return None, info

    info["device"] = pinned
    backend = _backend_flag()
    idx = int(pinned["index"])
    try:
        if backend is not None:
            cap = cv2.VideoCapture(idx, backend)
        else:
            cap = cv2.VideoCapture(idx)
    except Exception as exc:  # noqa: BLE001
        info["reason"] = f"open_failed: {exc}"
        return None, info

    if not cap.isOpened():
        info["reason"] = (
            "device_not_opened: exclusive lock / HDCP / wrong index? "
            "Quit 4K Capture Utility / OBS exclusive and retry"
        )
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass
        return None, info

    # Apply format hints (best-effort)
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        cap.set(cv2.CAP_PROP_FPS, float(fps))
    except Exception:  # noqa: BLE001
        pass

    info["ok"] = True
    info["reason"] = None
    # Read back actual props
    try:
        info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
        info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
        info["fps"] = float(cap.get(cv2.CAP_PROP_FPS)) or fps
    except Exception:  # noqa: BLE001
        pass
    return cap, info


def is_frame_black(frame: Any, *, mean_luma_max: float = 8.0) -> bool:
    """Heuristic black-frame detector (HDCP / exclusive lock symptom)."""
    cv2 = _cv2()
    if cv2 is None or frame is None:
        return True
    try:
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        return float(gray.mean()) <= mean_luma_max
    except Exception:  # noqa: BLE001
        return True


if __name__ == "__main__":
    print(f"opencv_available={opencv_available()} err={opencv_error()}")
    for d in list_devices():
        tag = "ELGATO" if d.get("is_elgato") else "other"
        print(f"  [{tag}] index={d['index']} name={d['name']!r} backend={d['backend']}")
    pinned = find_elgato()
    print(f"pinned: {pinned}")
