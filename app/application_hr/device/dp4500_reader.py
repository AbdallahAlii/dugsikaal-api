from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import secrets
from dataclasses import dataclass
from typing import Optional


class DP4500Error(RuntimeError):
    pass


@dataclass
class CaptureResult:
    template_bytes: bytes
    device_name: Optional[str] = None
    device_serial: Optional[str] = None
    quality: Optional[int] = None
    raw: dict | None = None


class DP4500Reader:
    """
    Reader adapter with multiple modes:
      - MOCK: returns random bytes
      - EXE: calls an external capture program (recommended now)
      - DLL: placeholder (later bind HID SDK)
    """

    def __init__(
        self,
        *,
        mode: str,
        exe_path: str = "",
        exe_args: str = "",
        timeout_sec: int = 15,
        dll_path: str = "",
        logger=None,
    ):
        self.mode = (mode or "MOCK").upper()
        self.exe_path = exe_path
        self.exe_args = exe_args
        self.timeout_sec = int(timeout_sec or 15)
        self.dll_path = dll_path
        self.log = logger

    def capture(self) -> CaptureResult:
        if self.mode == "MOCK":
            # Stable “fake template” for testing (still random per call)
            b = secrets.token_bytes(512)
            return CaptureResult(template_bytes=b, device_name="MOCK-DP4500", device_serial="MOCK")

        if self.mode == "EXE":
            return self._capture_via_exe()

        if self.mode == "DLL":
            # You will implement later using HID SDK
            raise DP4500Error("DP4500 DLL mode not implemented yet.")

        raise DP4500Error(f"Unknown DP4500_MODE: {self.mode}")

    def _capture_via_exe(self) -> CaptureResult:
        if not self.exe_path or not os.path.exists(self.exe_path):
            raise DP4500Error(f"DP4500_EXE_PATH not found: {self.exe_path}")

        args = [self.exe_path]
        if self.exe_args:
            # simple split; if you need quoting, pass exact args list instead
            args += self.exe_args.split()

        t0 = time.time()
        if self.log:
            self.log.info("DP4500(EXE) starting capture. exe=%s args=%s timeout=%ss", self.exe_path, args, self.timeout_sec)

        try:
            cp = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise DP4500Error(f"DP4500 capture timed out after {self.timeout_sec}s")

        dt = time.time() - t0
        stdout = (cp.stdout or "").strip()
        stderr = (cp.stderr or "").strip()

        if self.log:
            self.log.info("DP4500(EXE) finished. rc=%s duration=%.2fs", cp.returncode, dt)
            if stderr:
                self.log.warning("DP4500(EXE) stderr: %s", stderr[:500])

        if cp.returncode != 0:
            raise DP4500Error(f"DP4500 capture program failed rc={cp.returncode}: {stderr[:200]}")

        # EXPECTATION: your EXE prints JSON to stdout with a base64 template
        # Example expected stdout JSON:
        # {
        #   "ok": true,
        #   "template_b64": "...",
        #   "device_name": "HID DigitalPersona",
        #   "device_serial": "....",
        #   "quality": 78
        # }
        try:
            payload = json.loads(stdout)
        except Exception:
            raise DP4500Error("DP4500 EXE did not output valid JSON on stdout.")

        if not payload.get("ok", False):
            raise DP4500Error(payload.get("error") or "Finger not captured (device returned ok=false).")

        template_b64 = payload.get("template_b64")
        if not template_b64:
            raise DP4500Error("DP4500 EXE JSON missing template_b64.")

        try:
            template_bytes = base64.b64decode(template_b64)
        except Exception:
            raise DP4500Error("DP4500 EXE template_b64 is not valid base64.")

        return CaptureResult(
            template_bytes=template_bytes,
            device_name=payload.get("device_name"),
            device_serial=payload.get("device_serial"),
            quality=payload.get("quality"),
            raw=payload,
        )
