#!/usr/bin/env python3
"""
Shared swipe results schema + writers for swipe_test / swipe_ui (schema v2).

Schema v2 adds: hardware, firmware_defaults, acceptance thresholds, idle_dz
object, calibration object, void gates, lag_offset_ms, richer tests[].metrics.

Import:
  from swipe_results_lib import new_report, add_test, write_results, SCHEMA_VERSION
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 2

# Optional local imports (same package dir) — keep soft so CLI tools still load
try:
    from swipe_acceptance import ACCEPTANCE, MATRIX_LABELS, acceptance_block
except ImportError:  # pragma: no cover
    ACCEPTANCE = {}
    MATRIX_LABELS = ()
    def acceptance_block() -> dict[str, Any]:
        return {}


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def results_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    return d


def git_hint() -> dict[str, str]:
    root = repo_root()
    out: dict[str, str] = {}
    try:
        out["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        pass
    try:
        out["commit"] = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        pass
    return out


def new_report(
    *,
    port: str,
    version: str,
    source: str,
    capture_device: str | None = None,
    capture_index: int | None = None,
    lag_offset_ms: float | None = None,
    usb2_baud: int = 4_000_000,
    firmware_defaults: dict[str, Any] | None = None,
    void: bool | None = None,
    void_reason: str | None = None,
) -> dict[str, Any]:
    """
    Create a schema v2 report skeleton.

    Expected shape (Tools lock):
      schema_version: 2
      source: swipe_ui | swipe_test
      timestamp_utc, port, version, git{branch,commit}
      hardware: {usb2_baud, capture_device, capture_index, lag_offset_ms}
      firmware_defaults: {C, P, idle_dz, steady, trim}
      acceptance: {version, thresholds, matrix_labels, ...}
      tests: [{name, status, detail, metrics{}, late_ms?, expected?, got?, void?}]
      idle_dz: {suggested, applied, rx_p99, ry_p99, samples}
      calibration: {hip{...}, ads{...}}
      void, void_reason, void_reasons, preflight{}
      roi: {x,y,w,h}
      yolo: {backend, model, conf}
      yolo_t0 / yolo_t1: [{cls, conf, xyxy|cxcywh}]
      delta: {dx_px, dy_px, d_px, yaw_deg_est?}
      overall: PASS|FAIL|PARTIAL|null
      notes: []
    """
    now = datetime.now(timezone.utc)
    fw = firmware_defaults or {
        "C": 5046.0,
        "P": 0.40,
        "idle_dz": 0,
        "steady": 0,
        "trim": [0, 0],
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "port": port,
        "version": version,
        "git": git_hint(),
        "hardware": {
            "usb2_baud": usb2_baud,
            "capture_device": capture_device,
            "capture_index": capture_index,
            "lag_offset_ms": lag_offset_ms,
        },
        "firmware_defaults": fw,
        "acceptance": acceptance_block(),
        "tests": [],
        "idle_dz": {
            "suggested": None,
            "applied": None,
            "rx_p99": None,
            "ry_p99": None,
            "samples": None,
        },
        "calibration": {
            "hip": {
                "total": None,
                "status": None,
                "sens_hint": "look=2",
            },
            "ads": {
                "total": None,
                "status": None,
                "sens_hint": "aim=1.50",
                "ads_held": True,
            },
        },
        "void": void,
        "void_reason": void_reason,
        "void_reasons": [],
        "preflight": None,
        # ROI + YOLO T0→T1 bbox-center compare (Dylan schema v2)
        "roi": None,  # {x,y,w,h}
        "yolo": None,  # {backend: ultralytics|onnx, model, conf}
        "yolo_t0": [],  # [{cls, conf, xyxy|cxcywh}]
        "yolo_t1": [],
        "delta": None,  # {dx_px, dy_px, d_px, yaw_deg_est?}
        "overall": None,
        "notes": [],
        # v1 compat mirrors (still written; readers may use them)
        "idle_dz_suggested": None,
        "totals": {},
        "late_ms_samples": [],
    }
    return report


def apply_preflight(report: dict[str, Any], preflight_fields: dict[str, Any]) -> None:
    """
    Merge output of swipe_preflight.preflight_schema_fields(...) into report.

    Stamps: void, void_reason, void_reasons, lag_offset_ms (hardware),
    capture_device/index, preflight{}.
    """
    report["void"] = preflight_fields.get("void")
    report["void_reason"] = preflight_fields.get("void_reason")
    report["void_reasons"] = list(preflight_fields.get("void_reasons") or [])
    report["preflight"] = preflight_fields.get("preflight")
    hw = report.setdefault("hardware", {})
    if preflight_fields.get("lag_offset_ms") is not None:
        hw["lag_offset_ms"] = preflight_fields.get("lag_offset_ms")
    if preflight_fields.get("capture_device") is not None:
        hw["capture_device"] = preflight_fields.get("capture_device")
    if preflight_fields.get("capture_index") is not None:
        hw["capture_index"] = preflight_fields.get("capture_index")




def set_yolo_roi(
    report: dict[str, Any],
    *,
    roi: dict[str, Any] | None = None,
    yolo: dict[str, Any] | None = None,
    yolo_t0: list[Any] | None = None,
    yolo_t1: list[Any] | None = None,
    delta: dict[str, Any] | None = None,
) -> None:
    """
    Stamp ROI + YOLO T0/T1 + center-delta into schema v2.

    Preferred flow (peer HUD):
      snap T0 in ROI → 360 → snap T1 → bbox_center_delta(T0, T1)
    Use tools/yolo_roi.schema_yolo_block(...) or pass dicts directly.
    """
    if roi is not None:
        report["roi"] = roi
    if yolo is not None:
        report["yolo"] = yolo
    if yolo_t0 is not None:
        report["yolo_t0"] = list(yolo_t0)
    if yolo_t1 is not None:
        report["yolo_t1"] = list(yolo_t1)
    if delta is not None:
        report["delta"] = delta


def apply_yolo_block(report: dict[str, Any], block: dict[str, Any]) -> None:
    """Merge tools/yolo_roi.schema_yolo_block(...) into report."""
    set_yolo_roi(
        report,
        roi=block.get("roi"),
        yolo=block.get("yolo"),
        yolo_t0=block.get("yolo_t0"),
        yolo_t1=block.get("yolo_t1"),
        delta=block.get("delta"),
    )


def add_test(
    report: dict[str, Any],
    name: str,
    *,
    status: str,
    detail: str = "",
    metrics: dict[str, Any] | None = None,
    late_ms: float | None = None,
    expected: Any = None,
    got: Any = None,
    void: bool | None = None,
    **extra: Any,
) -> None:
    """status: PASS | FAIL | SOFT | SKIP | INFO | MEASURED | VOID"""
    entry: dict[str, Any] = {"name": name, "status": status}
    if detail:
        entry["detail"] = detail
    if metrics is not None:
        entry["metrics"] = metrics
    if late_ms is not None:
        entry["late_ms"] = late_ms
        # v1 mirror
        report.setdefault("late_ms_samples", []).append(late_ms)
    if expected is not None:
        entry["expected"] = expected
    if got is not None:
        entry["got"] = got
    if void is not None:
        entry["void"] = void
    entry.update(extra)
    report["tests"].append(entry)


def set_idle_dz(
    report: dict[str, Any],
    *,
    suggested: int | None,
    applied: int | None = None,
    rx_p99: int | None = None,
    ry_p99: int | None = None,
    samples: int | None = None,
) -> None:
    block = report.setdefault("idle_dz", {})
    block["suggested"] = suggested
    block["applied"] = applied
    block["rx_p99"] = rx_p99
    block["ry_p99"] = ry_p99
    block["samples"] = samples
    report["idle_dz_suggested"] = suggested  # v1 mirror


def set_calibration(
    report: dict[str, Any],
    *,
    hip_total: int | None = None,
    hip_status: str | None = None,
    ads_total: int | None = None,
    ads_status: str | None = None,
    ads_held: bool = True,
) -> None:
    cal = report.setdefault("calibration", {})
    hip = cal.setdefault("hip", {"sens_hint": "look=2"})
    ads = cal.setdefault("ads", {"sens_hint": "aim=1.50", "ads_held": True})
    if hip_total is not None:
        hip["total"] = hip_total
        report.setdefault("totals", {})["hip"] = hip_total
    if hip_status is not None:
        hip["status"] = hip_status
    if ads_total is not None:
        ads["total"] = ads_total
        report.setdefault("totals", {})["ads"] = ads_total
    if ads_status is not None:
        ads["status"] = ads_status
    ads["ads_held"] = ads_held


def compute_overall(report: dict[str, Any]) -> str | None:
    """
    Derive overall from tests + void.

    - void True → null (do not FAIL firmware on void)
    - any FAIL → FAIL
    - any SOFT / PARTIAL mix → PARTIAL
    - all PASS → PASS
    - empty → null
    """
    if report.get("void") is True:
        report["overall"] = None
        return None
    tests = report.get("tests") or []
    if not tests:
        report["overall"] = None
        return None
    statuses = [str(t.get("status", "")).upper() for t in tests]
    # Ignore VOID/INFO/SKIP/MEASURED for overall rollup
    scored = [s for s in statuses if s in ("PASS", "FAIL", "SOFT", "PARTIAL")]
    if not scored:
        report["overall"] = None
        return None
    if any(s == "FAIL" for s in scored):
        report["overall"] = "FAIL"
    elif any(s in ("SOFT", "PARTIAL") for s in scored):
        report["overall"] = "PARTIAL"
    elif all(s == "PASS" for s in scored):
        report["overall"] = "PASS"
    else:
        report["overall"] = "PARTIAL"
    return report["overall"]


def write_results(report: dict[str, Any], prefix: str = "swipe_results") -> tuple[str, str]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(results_dir(), f"{prefix}_{ts}")
    json_path = base + ".json"
    txt_path = base + ".txt"
    # Ensure overall is filled if caller forgot
    if report.get("overall") is None and (report.get("tests") or report.get("void") is True):
        compute_overall(report)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(_format_txt(report))
    return json_path, txt_path


def _format_txt(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("MAKCU swipe results")
    lines.append(f"schema_version: {report.get('schema_version')}")
    lines.append(f"source: {report.get('source')}")
    lines.append(f"timestamp_utc: {report.get('timestamp_utc')}")
    lines.append(f"port: {report.get('port')}")
    lines.append(f"version: {report.get('version')}")
    g = report.get("git") or {}
    if g:
        lines.append(f"git: {g.get('branch', '?')} @ {g.get('commit', '?')}")
    lines.append(f"overall: {report.get('overall')}")

    # v2 void / lag
    if report.get("void") is not None:
        lines.append(f"void: {report.get('void')}")
    if report.get("void_reason"):
        lines.append(f"void_reason: {report.get('void_reason')}")
    reasons = report.get("void_reasons") or []
    if reasons:
        lines.append("void_reasons: " + ", ".join(str(r) for r in reasons))

    hw = report.get("hardware") or {}
    if hw:
        lines.append(
            "hardware: "
            f"usb2_baud={hw.get('usb2_baud')} "
            f"capture={hw.get('capture_device')!r}@{hw.get('capture_index')} "
            f"lag_offset_ms={hw.get('lag_offset_ms')}"
        )

    fw = report.get("firmware_defaults") or {}
    if fw:
        lines.append(
            "firmware_defaults: "
            + ", ".join(f"{k}={v}" for k, v in fw.items())
        )

    acc = report.get("acceptance") or {}
    if acc:
        thr = acc.get("thresholds") or ACCEPTANCE
        lines.append(
            "acceptance: "
            f"yaw≤{thr.get('yaw_pass_deg')}°/soft{thr.get('yaw_soft_deg')}° "
            f"ecc≥{thr.get('ecc_pass')}/{thr.get('ecc_soft')} "
            f"phase≥{thr.get('phase_pass')}/{thr.get('phase_soft')} "
            f"ratio={thr.get('hip_ads_ratio')}±{float(thr.get('hip_ads_ratio_tol', 0)*100):.0f}%"
        )
        labels = acc.get("matrix_labels") or list(MATRIX_LABELS)
        if labels:
            lines.append("matrix_labels: " + " | ".join(labels))

    idle = report.get("idle_dz") or {}
    if idle and idle.get("suggested") is not None:
        lines.append(
            f"idle_dz: suggested={idle.get('suggested')} applied={idle.get('applied')} "
            f"rx_p99={idle.get('rx_p99')} ry_p99={idle.get('ry_p99')} "
            f"samples={idle.get('samples')}"
        )
    elif report.get("idle_dz_suggested") is not None:
        lines.append(f"idle_dz_suggested: {report.get('idle_dz_suggested')}")

    cal = report.get("calibration") or {}
    if cal:
        hip = cal.get("hip") or {}
        ads = cal.get("ads") or {}
        if hip.get("total") is not None or ads.get("total") is not None:
            lines.append(
                f"calibration: hip total={hip.get('total')} status={hip.get('status')} "
                f"({hip.get('sens_hint')}); "
                f"ads total={ads.get('total')} status={ads.get('status')} "
                f"({ads.get('sens_hint')}, ads_held={ads.get('ads_held')})"
            )

    totals = report.get("totals") or {}
    if totals:
        lines.append(
            "totals: " + ", ".join(f"{k}={v}" for k, v in totals.items())
        )
    late = report.get("late_ms_samples") or []
    if late:
        lines.append(
            "late_ms_samples: "
            + ", ".join(f"{x:.1f}" if isinstance(x, float) else str(x) for x in late)
        )

    roi = report.get("roi")
    if roi:
        lines.append(
            f"roi: x={roi.get('x')} y={roi.get('y')} w={roi.get('w')} h={roi.get('h')}"
        )
    yolo = report.get("yolo")
    if yolo:
        lines.append(
            f"yolo: backend={yolo.get('backend')} model={yolo.get('model')} "
            f"conf={yolo.get('conf')}"
        )
    if report.get("yolo_t0") is not None:
        lines.append(f"yolo_t0: {len(report.get('yolo_t0') or [])} det(s)")
    if report.get("yolo_t1") is not None:
        lines.append(f"yolo_t1: {len(report.get('yolo_t1') or [])} det(s)")
    delta = report.get("delta")
    if delta:
        lines.append(
            f"delta: dx_px={delta.get('dx_px')} dy_px={delta.get('dy_px')} "
            f"d_px={delta.get('d_px')} yaw_deg_est={delta.get('yaw_deg_est')}"
        )

    pf = report.get("preflight")
    if isinstance(pf, dict):
        lines.append(f"preflight.pass: {pf.get('pass')}")
        gates = pf.get("gates") or {}
        if gates:
            lines.append("preflight.gates:")
            for k, v in gates.items():
                lines.append(f"  [{'PASS' if v else 'VOID'}] {k}")

    lines.append("")
    lines.append("tests:")
    for t in report.get("tests") or []:
        detail = t.get("detail") or ""
        bits: list[str] = []
        if t.get("late_ms") is not None:
            bits.append(f"late_ms={t.get('late_ms')}")
        if t.get("expected") is not None:
            bits.append(f"expected={t.get('expected')}")
        if t.get("got") is not None:
            bits.append(f"got={t.get('got')}")
        if t.get("metrics"):
            bits.append(f"metrics={t.get('metrics')}")
        if t.get("void") is not None:
            bits.append(f"void={t.get('void')}")
        # leftover extras
        skip = {
            "name", "status", "detail", "metrics", "late_ms",
            "expected", "got", "void",
        }
        extra = {k: v for k, v in t.items() if k not in skip}
        if extra:
            bits.append(str(extra))
        extra_s = ("  " + " ".join(bits)) if bits else ""
        lines.append(
            f"  [{t.get('status')}] {t.get('name')}"
            + (f" — {detail}" if detail else "")
            + extra_s
        )
    notes = report.get("notes") or []
    if notes:
        lines.append("")
        lines.append("notes:")
        for n in notes:
            lines.append(f"  - {n}")
    lines.append("")
    return "\n".join(lines)


# --- v1 reader helper (trivial) ---------------------------------------------

def load_report(path: str) -> dict[str, Any]:
    """Load JSON report (v1 or v2)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    r = new_report(port="COM5", version="kmbox demo", source="swipe_results_lib")
    add_test(r, "demo", status="INFO", detail="schema v2 smoke")
    jp, tp = write_results(r, prefix="schema_v2_smoke")
    print(jp)
    print(tp)
