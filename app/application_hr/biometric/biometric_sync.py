from __future__ import annotations

import os
import time
import datetime
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from zk import ZK, const  # provided by pyzk

load_dotenv()

# -----------------------------------
# Config from environment (.env)
# -----------------------------------

# Base URL of your ERP backend API
# e.g. "http://localhost:2000" or "https://erp.yourdomain.com"
API_BASE_URL = os.getenv("ERP_API_BASE_URL", "http://localhost:2000")

# If this agent should only sync one company, put its ID here.
# If empty, agent will sync devices for ALL companies.
AGENT_COMPANY_ID = os.getenv("BIOMETRIC_AGENT_COMPANY_ID")

# How often to pull data from devices (seconds)
PULL_FREQUENCY_SECONDS = int(os.getenv("BIOMETRIC_PUNCH_PULL_FREQUENCY", "3600"))

# Optional token to secure API calls from agent → backend
AGENT_AUTH_TOKEN = os.getenv("BIOMETRIC_AGENT_TOKEN", "")

# Map ZK punch values to IN/OUT
DEVICE_PUNCH_IN = [0, 4]
DEVICE_PUNCH_OUT = [1, 5]


# --------------------
# API helpers
# --------------------
def get_devices_from_server() -> List[Dict[str, Any]]:
    """
    Call /api/hr/biometric-devices/agent-config to fetch active devices.

    Expected response from Flask:
    {
      "success": true,
      "message": "...",
      "data": [
        {
          "id": 1,
          "company_id": 1,
          "device_code": "MOF-HQ-ZK-1",
          "name": "MOF HQ Main Gate",
          "ip": "192.168.0.209",
          "port": 4370,
          "password": 0,
          "timeout": 30
        },
        ...
      ]
    }
    """
    params: Dict[str, Any] = {}
    if AGENT_COMPANY_ID:
        params["company_id"] = AGENT_COMPANY_ID

    headers: Dict[str, str] = {}
    if AGENT_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AGENT_AUTH_TOKEN}"

    url = f"{API_BASE_URL}/api/hr/biometric-devices/agent-config"
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("data", [])


def send_checkin_to_api(
    *,
    company_id: int,
    device_code: str,
    user_id: str,
    ts: datetime.datetime,
    punch: int,
    status: int,
) -> None:
    """
    Send a single ZK attendance log to your ERP backend as EmployeeCheckin.
    """

    if punch in DEVICE_PUNCH_IN:
        log_type = "In"   # matches CheckinLogTypeEnum
    elif punch in DEVICE_PUNCH_OUT:
        log_type = "Out"
    else:
        log_type = "In"

    payload = {
        "company_id": company_id,
        # This maps to Employee.attendance_device_id:
        "device_employee_id": str(user_id),
        "log_time": ts.isoformat(),
        "log_type": log_type,
        "source": "Device",
        # BiometricDevice.code, stored in EmployeeCheckin.device_id
        "device_id": device_code,
        "raw_payload": {
            "user_id": user_id,
            "punch": punch,
            "status": status,
        },
    }

    headers = {"Content-Type": "application/json"}
    if AGENT_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AGENT_AUTH_TOKEN}"

    resp = requests.post(
        f"{API_BASE_URL}/api/hr/employee-checkin",
        json=payload,
        headers=headers,
        timeout=15,
    )
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    print(f"[{device_code}] API response:", resp.status_code, data)


# --------------------
# Device sync logic
# --------------------
def sync_one_device(device_cfg: Dict[str, Any]) -> None:
    """
    Connects to one ZK device and sends all attendance logs to ERP API.
    device_cfg comes from /biometric-devices/agent-config.
    """
    device_code: str = device_cfg["device_code"]
    company_id: int = int(device_cfg["company_id"])

    print(f"\n=== Syncing device {device_code} (company_id={company_id}) ===")

    zk = ZK(
        device_cfg["ip"],
        port=device_cfg.get("port", 4370),
        timeout=device_cfg.get("timeout", 30),
        password=device_cfg.get("password", 0),
        force_udp=False,
        ommit_ping=False,
    )

    conn = None
    try:
        print(f"[{device_code}] Connecting to {device_cfg['ip']}...")
        conn = zk.connect()
        print(f"[{device_code}] Disabling device while syncing...")
        conn.disable_device()

        print(f"[{device_code}] Fetching attendance...")
        attendances = conn.get_attendance() or []
        print(f"[{device_code}] Got {len(attendances)} records")

        for a in attendances:
            # a has: user_id, timestamp, punch, status, uid
            print(
                f"[{device_code}] Sending: user={a.user_id}, "
                f"time={a.timestamp}, punch={a.punch}, status={a.status}"
            )
            send_checkin_to_api(
                company_id=company_id,
                device_code=device_code,
                user_id=a.user_id,
                ts=a.timestamp,
                punch=a.punch,
                status=a.status,
            )

        # Optional: clear logs after successful sync
        # conn.clear_attendance()

        print(f"[{device_code}] Sync done. Re-enabling device...")
        conn.enable_device()

    except Exception as e:
        print(f"[{device_code}] Device sync error:", e)
    finally:
        if conn:
            conn.disconnect()


def main_loop() -> None:
    try:
        devices = get_devices_from_server()
    except Exception as e:
        print("Failed to fetch devices from server:", e)
        return

    print(f"Loaded {len(devices)} devices from server")
    for dev in devices:
        sync_one_device(dev)


if __name__ == "__main__":
    print("Starting biometric sync agent...")
    print(f"ERP API base: {API_BASE_URL}")
    print(f"BIOMETRIC_AGENT_COMPANY_ID={AGENT_COMPANY_ID}")
    print(f"Pull frequency: {PULL_FREQUENCY_SECONDS} seconds")

    while True:
        main_loop()
        print(f"Sleeping for {PULL_FREQUENCY_SECONDS} seconds...")
        time.sleep(PULL_FREQUENCY_SECONDS)
