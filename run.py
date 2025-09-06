#!/usr/bin/env python3
# run.py — entrypoint for CoreUpdateCLI (with preflight + platform banner)

import os, sys, platform
from datetime import datetime

try:
    import part0_platform
    import part1_bootstrap
    import part2_helpers
    import part3_health
    import part4_menus
    import part5_main
except ImportError as e:
    print(f"[FATAL] Missing module: {e}. Ensure all partX files exist.")
    sys.exit(1)

from part0_platform import get_system_info, has_cap, pm_name
from part1_bootstrap import console
from part2_helpers import ensure_deps

VERSION = "v1.0"
BUILD_DATE = datetime.now().strftime("%Y-%m-%d")

def _detect_env_type():
    if os.environ.get("PIPENV_ACTIVE") == "1":
        return "pipenv"
    in_venv = (hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix))
    if in_venv or os.environ.get("COREUPDATE_ENV_ACTIVE") == "1":
        return "venv"
    return "system"

def _clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def _preflight():
    # Prepare deps only for supported features on this OS
    if has_cap("apps"):
        ensure_deps(apps=True)
    if has_cap("updates") or has_cap("drivers"):
        ensure_deps(updates=True, drivers=True)

def main():
    _clear_screen()
    sysinfo = get_system_info()
    env_type = _detect_env_type()

    # Header
    console.print(f"[bold blue]=== Core Update CLI {VERSION} ({BUILD_DATE}) ===[/]")
    console.print(
        f"[grey]{sysinfo['OSShort']} • {sysinfo.get('CPU') or '-'} • RAM: {part0_platform.bytes_human(sysinfo.get('TotalRAMBytes'))} • "
        f"Arch: {sysinfo['Arch']} • Python {platform.python_version()}[/]"
    )
    caps = []
    if has_cap("apps"): caps.append(f"Apps via {pm_name()}")
    if has_cap("updates"): caps.append("Windows Updates")
    if has_cap("drivers"): caps.append("Driver Updates")
    if has_cap("power_plans"): caps.append("Power Plans")
    if has_cap("restore_point"): caps.append("Restore Points")
    caps.append("Junk Clean")
    console.print("[grey]Capabilities: " + ", ".join(caps) + f" | Env: {env_type}[/]\n")

    # Preflight only for supported features
    _preflight()

    # Hand off
    part5_main.main(version=VERSION, build_date=BUILD_DATE)

if __name__ == "__main__":
    main()
