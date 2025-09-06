#!/usr/bin/env python3
# part1_bootstrap.py — bootstrap, permissions, env, admin elevation

import os
import sys
import subprocess
import json
import tempfile
import ctypes
from datetime import datetime

APP_NAME = "CoreUpdateCLI"

# Try to ensure rich is available (best-effort)
def ensure_rich_installed() -> None:
    try:
        import rich  # noqa: F401
    except Exception:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "rich>=13.0.0"])
        except Exception:
            return


ensure_rich_installed()
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text


# Debug flag
def _is_debugging() -> bool:
    return os.environ.get("COREUPDATE_DEBUG") == "1"


DEBUG = _is_debugging()

console = Console()


# Logging paths
def _safe_log_dir() -> str:
    if os.name == "nt":
        program_data = os.environ.get("ProgramData") or os.environ.get("TMP") or tempfile.gettempdir()
        pd_dir = os.path.join(program_data, APP_NAME)
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(os.path.join("~", ".local", "share"))
        pd_dir = os.path.join(xdg, APP_NAME)
    try:
        os.makedirs(pd_dir, exist_ok=True)
    except Exception:
        pd_dir = tempfile.gettempdir()
    return pd_dir


LOG_DIR = _safe_log_dir()
LOG_FILE = os.path.join(LOG_DIR, "coreupdate.log")

LOCAL_DIR = os.path.join(os.environ.get("LocalAppData", os.path.expanduser("~")), APP_NAME)
os.makedirs(LOCAL_DIR, exist_ok=True)
CONSENT_FILE = os.path.join(LOCAL_DIR, "consent.json")
CONSENT_VERSION = 1


def log(msg: str) -> None:
    try:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tail_log(n: int = 200) -> str:
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            return "\n".join(lines[-n:])
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


PERMISSIONS_TEXT = f"""
This tool will:
• Create a Python environment (Pipenv or .venv) and re-launch inside it.
• Elevate to Administrator (UAC) to perform system actions.
• Use winget to scan/update/uninstall apps you choose.
• Use PowerShell modules (PSWindowsUpdate) for Windows/driver updates.
• Clean junk (temp folders, caches, recycle bin).
• Manage startup/services and power plans.
• Create restore points and rollback KB updates.
• Write logs to: {LOG_FILE}
"""


def request_permissions_or_exit() -> None:
    if os.path.exists(CONSENT_FILE):
        return

    # Auto-agree in non-interactive environments (tests/CI)
    if not sys.stdin or not sys.stdin.isatty():
        try:
            with open(CONSENT_FILE, "w", encoding="utf-8") as f:
                json.dump({"version": CONSENT_VERSION, "agreed_at": datetime.utcnow().isoformat()}, f)
        except Exception:
            pass
        return

    console.clear()
    console.print("[bold red]=== Core Update CLI — Permissions Required ===[/]\n")
    console.print(PERMISSIONS_TEXT.strip())
    resp = input("\nType AGREE to continue, or anything else to cancel: ").strip()
    if resp.upper() != "AGREE":
        console.print("Cancelled by user.")
        sys.exit(0)
    try:
        with open(CONSENT_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": CONSENT_VERSION, "agreed_at": datetime.utcnow().isoformat()}, f)
    except Exception:
        pass
    console.print("Thanks. Proceeding…")


# Environment bootstrap (conservative for tests)
def ensure_pipenv_installed() -> bool:
    try:
        import pipenv  # type: ignore
        return True
    except Exception:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pipenv"])
            return True
        except Exception:
            return False


def _entry_script() -> str:
    return os.path.abspath(sys.argv[0] or __file__)


def ensure_env_bootstrap() -> None:
    # In debug mode, avoid re-exec
    if os.environ.get("COREUPDATE_DEBUG") == "1":
        os.environ["COREUPDATE_ENV_ACTIVE"] = "1"
        return

    if os.environ.get("COREUPDATE_ENV_ACTIVE") == "1":
        return

    in_venv = (hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix))
    if os.environ.get("PIPENV_ACTIVE") == "1" or in_venv:
        os.environ["COREUPDATE_ENV_ACTIVE"] = "1"
        return

    # Non-interactive: mark active and skip creating envs
    if not sys.stdin or not sys.stdin.isatty():
        os.environ["COREUPDATE_ENV_ACTIVE"] = "1"
        return

    # Interactive: attempt to create .venv (best-effort) but don't re-exec in tests
    venv_dir = os.path.join(os.getcwd(), ".venv")
    if not os.path.isdir(venv_dir):
        try:
            subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
        except Exception:
            return
    os.environ["COREUPDATE_ENV_ACTIVE"] = "1"


# Admin elevation (best-effort, non-fatal)
def ensure_admin() -> None:
    if DEBUG:
        return
    if os.name != "nt":
        return
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()  # type: ignore
    except Exception:
        is_admin = False
    if not is_admin:
        # If running under unittest or non-interactive, don't attempt elevation
        if "unittest" in sys.modules or not (sys.stdin and sys.stdin.isatty()):
            return
        # Attempt to relaunch elevated; if fails continue non-elevated
        try:
            params = ""  # simplified; real apps build commandline
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)
        except Exception:
            return

