#!/usr/bin/env python3
# part0_platform.py — OS & device detection + capabilities

import os
import platform
import shutil
import subprocess
import json

OS_NAME = platform.system().lower()  # 'windows', 'darwin', 'linux'
ARCH = platform.machine()

def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)

def _windows_info():
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
[PSCustomObject]@{
  Manufacturer = $cs.Manufacturer
  Model = $cs.Model
  TotalRAMBytes = [int64]$cs.TotalPhysicalMemory
  OSName = $os.Caption
  OSVersion = $os.Version
  CPU = $cpu.Name
  GPU = $gpu.Name
} | ConvertTo-Json
"""
    rc, out = _run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps])
    if rc == 0 and out:
        try: return json.loads(out)
        except: pass
    # Fallback minimal
    return {
        "Manufacturer": None, "Model": None,
        "TotalRAMBytes": None, "OSName": platform.platform(),
        "OSVersion": platform.version(), "CPU": platform.processor(), "GPU": None
    }

def _mac_info():
    # system_profiler can be slow; we ask minimal domains first
    rc1, hw = _run(["system_profiler", "-json", "SPHardwareDataType"])
    rc2, sp = _run(["system_profiler", "-json", "SPDisplaysDataType"])
    info = {}
    try:
        if rc1 == 0 and hw:
            j = json.loads(hw)
            hwdata = (j.get("SPHardwareDataType") or [{}])[0]
            info["Manufacturer"] = "Apple"
            info["Model"] = hwdata.get("machine_model") or hwdata.get("model_name")
            info["TotalRAMBytes"] = None  # Apple only reports in GB; leave None
            info["CPU"] = hwdata.get("cpu_type") or hwdata.get("chip_type")
            info["OSName"] = "macOS"
            info["OSVersion"] = platform.mac_ver()[0]
        if rc2 == 0 and sp:
            j2 = json.loads(sp)
            gpus = j2.get("SPDisplaysDataType") or []
            info["GPU"] = (gpus[0].get("sppci_model") if gpus else None)
    except Exception:
        pass
    # Fill fallbacks
    info.setdefault("OSName", "macOS")
    info.setdefault("OSVersion", platform.mac_ver()[0])
    info.setdefault("CPU", platform.processor())
    info.setdefault("GPU", None)
    return info

def _linux_info():
    # Try lshw (if present)
    if shutil.which("lshw"):
        rc, out = _run(["lshw","-json","-short"])
        if rc == 0 and out:
            try:
                data = json.loads(out)
            except Exception:
                data = None
            # Not strictly needed for CLI; provide minimal set:
    # Minimal /proc fallbacks
    cpu = None
    try:
        with open("/proc/cpuinfo","r") as f:
            for line in f:
                if "model name" in line:
                    cpu = line.split(":",1)[1].strip()
                    break
    except Exception:
        pass
    # Memory (kB) from /proc/meminfo
    mem_bytes = None
    try:
        with open("/proc/meminfo","r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    mem_bytes = kb * 1024
                    break
    except Exception:
        pass
    return {
        "Manufacturer": None,
        "Model": None,
        "TotalRAMBytes": mem_bytes,
        "OSName": "Linux",
        "OSVersion": platform.release(),
        "CPU": cpu or platform.processor(),
        "GPU": None,
    }

def bytes_human(n):
    if not n: return "-"
    units = ["B","KB","MB","GB","TB"]
    f = float(n); i = 0
    while f >= 1024 and i < len(units)-1:
        f /= 1024; i += 1
    return f"{f:.1f} {units[i]}"

def get_system_info():
    if OS_NAME == "windows":
        data = _windows_info()
    elif OS_NAME == "darwin":
        data = _mac_info()
    else:
        data = _linux_info()
    data["OSShort"] = {
        "windows": f"Windows {platform.release()}",
        "darwin": f"macOS {platform.mac_ver()[0]}",
        "linux": f"Linux {platform.release()}",
    }.get(OS_NAME, platform.platform())
    data["Arch"] = ARCH
    return data

# ---------------- Capability Matrix ----------------
# We centralize which features CoreUpdateCLI should expose per OS.
CAPABILITIES = {
    "windows": {
        "apps": True,          # winget
        "updates": True,       # PSWindowsUpdate
        "drivers": True,       # PSWindowsUpdate drivers/pnputil
        "power_plans": True,   # powercfg
        "restore_point": True, # Checkpoint-Computer
        "junk_clean": True,
    },
    "darwin": {
        "apps": True,          # brew (formulae & casks)
        "updates": False,
        "drivers": False,
        "power_plans": False,
        "restore_point": False,
        "junk_clean": True,
    },
    "linux": {
        "apps": False,         # (could add apt/dnf/pacman later)
        "updates": False,
        "drivers": False,
        "power_plans": False,
        "restore_point": False,
        "junk_clean": True,
    }
}

def has_cap(feature: str) -> bool:
    return CAPABILITIES.get(OS_NAME, {}).get(feature, False)

def pm_name() -> str:
    if OS_NAME == "windows": return "winget"
    if OS_NAME == "darwin":  return "brew"
    return "pkg-manager"

