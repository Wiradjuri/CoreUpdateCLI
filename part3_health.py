#!/usr/bin/env python3
# part3_health.py — Health Check feature with live progress + logs (streaming app scan)

import os, shutil, subprocess, re, json
import concurrent.futures
from typing import List

from part1_bootstrap import console, log, LOG_FILE
from part2_helpers import (
    winget_upgrade,
    ensure_deps,               # NEW: global dep guard
    resolve_winget_path,
)

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.layout import Layout

# ---------------- Junk scan / cleanup ----------------

def get_temp_paths() -> List[str]:
    return [
        os.path.expandvars(r"%TEMP%"),
        os.path.expandvars(r"%LOCALAPPDATA%\Temp"),
        r"C:\Windows\Temp"
    ]

def calc_size(paths: List[str]) -> int:
    total = 0
    for base in paths:
        if not os.path.exists(base): 
            continue
        for root, _, files in os.walk(base):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except Exception:
                    pass
    return total

def human_bytes(n: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    f = float(n); i = 0
    while f >= 1024 and i < len(units)-1:
        f /= 1024; i += 1
    return f"{f:.1f} {units[i]}"

def clean_junk() -> int:
    total = 0
    for d in get_temp_paths():
        if os.path.isdir(d):
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                try:
                    if os.path.isfile(p) or os.path.islink(p):
                        try: total += os.path.getsize(p)
                        except Exception: pass
                        os.remove(p)
                    elif os.path.isdir(p):
                        for root, _, files in os.walk(p):
                            for f in files:
                                try: total += os.path.getsize(os.path.join(root, f))
                                except Exception: pass
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass
    os.system("powershell -NoProfile -Command \"Clear-RecycleBin -Force -ErrorAction SilentlyContinue\"")
    return total

# ---------------- Helper: stream winget upgrades ----------------

def _stream_winget_upgrades(logs: List[str], layout: Layout, progress: Progress, task_id, phase_start: float, phase_end: float) -> List[dict]:
    """
    Stream 'winget upgrade --include-unknown' and parse rows as they arrive.
    Progress advances only within [phase_start, phase_end].
    """
    exe = resolve_winget_path()
    cmd = [exe, "upgrade", "--include-unknown"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8")
    except FileNotFoundError:
        logs.append("winget not found (install App Installer from Microsoft Store).")
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
        return []

    logs.append("Checking for app updates…")
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    apps: List[dict] = []
    header_seen = False
    sep_seen = False

    current_pct = phase_start
    def _bump():
        nonlocal current_pct
        step = (phase_end - phase_start) / 50.0
        current_pct = min(phase_end, current_pct + step)
        progress.update(task_id, completed=current_pct)

    # Read full output but with timeout to avoid hangs
    try:
        out, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        logs.append("winget scan timed out.")
        if len(logs) > 20: logs.pop(0)
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
        progress.update(task_id, completed=phase_end)
        return apps

    for line in (out or "").splitlines():
        line = line.rstrip()
        if not line:
            _bump()
            continue
        if re.match(r"^\s*Name\s+Id\s+Version\s+Available", line):
            header_seen = True; sep_seen = False; continue
        if header_seen and re.match(r"^\s*-{3,}", line):
            sep_seen = True; continue
        if not header_seen or not sep_seen:
            _bump(); continue

        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 4:
            name, pid, ver, avail = parts[:4]
            if pid.lower().startswith("no ") or name.lower().startswith("no "):
                _bump(); continue
            app = {"Id": pid, "Name": name, "Version": ver, "Available": avail}
            apps.append(app)
            logs.append(f"Found: {name} ({pid}) {ver or '?'} \u2192 {avail}")
            if len(logs) > 20: logs.pop(0)
            layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
            _bump()
        else:
            logs.append(line)
            if len(logs) > 20: logs.pop(0)
            layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
            _bump()

    progress.update(task_id, completed=phase_end)
    return apps

# ---------------- Helper: quiet Windows updates scan (no nested Live) ----------------

def _scan_windows_updates_quiet(logs: List[str], layout: Layout, progress: Progress, task_id, phase_start: float, phase_end: float) -> List[dict]:
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
if (-not (Get-PSRepository -Name 'PSGallery' -ErrorAction SilentlyContinue)) { Register-PSRepository -Default | Out-Null }
if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) { Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null }
if (-not (Get-Module -ListAvailable PSWindowsUpdate | Select-Object -First 1)) { Install-Module -Name PSWindowsUpdate -Scope CurrentUser -Force -AllowClobber -Repository PSGallery | Out-Null }
Import-Module PSWindowsUpdate -Force
$u = Get-WindowsUpdate -MicrosoftUpdate -IgnoreReboot -AcceptAll
$rows = @()
foreach ($x in $u) {
  $kb = $null
  if ($x.KB) { $kb = ($x.KB | Select-Object -First 1) }
  elseif ($x.Title -match 'KB\d{5,7}') { $kb = $Matches[0] }
  $rows += [PSCustomObject]@{
    Title = $x.Title
    KB    = $kb
    UpdateId = $x.UpdateID
    Categories = @($x.Categories | ForEach-Object { $_.Name })
  }
}
$rows | ConvertTo-Json -Depth 4
"""
    try:
        proc = subprocess.Popen(
            ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        logs.append("PowerShell not found.")
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
        progress.update(task_id, completed=phase_end)
        return []

    logs.append("Checking Windows updates…")
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    # Read output with timeout to avoid blocking indefinitely
    buf: List[str] = []
    try:
        out, _ = proc.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        proc.kill()
        logs.append("Windows update scan timed out.")
        if len(logs) > 20: logs.pop(0)
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
        progress.update(task_id, completed=phase_end)
        return []
    out = (out or "").strip()

    items: List[dict] = []
    try:
        j = json.loads(out) if out else []
        if isinstance(j, dict):
            j = [j]
        for it in (j or []):
            items.append({
                "Title": it.get("Title", ""),
                "KB": it.get("KB", None),
                "UpdateId": it.get("UpdateId", ""),
                "Categories": list(it.get("Categories", []) or []),
            })
    except Exception as e:
        logs.append(f"Windows update parse error: {e}")
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    if items:
        for u in items[:50]:
            title = (u.get("Title") or "").strip()
            logs.append(f"Windows Update: {title}")
            if len(logs) > 20: logs.pop(0)
            layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
            # bump progress incrementally for each reported update
            current = progress.tasks[0].completed if progress.tasks else phase_start
            next_pct = min(phase_end, current + ((phase_end - phase_start) / 40.0))
            progress.update(task_id, completed=next_pct)
    else:
        logs.append("No Windows updates reported.")
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    progress.update(task_id, completed=phase_end)
    return items

# ---------------- Health Check (live UI) ----------------

def health_check():
    # Global self-heal for Health Check (apps & updates paths)
    if not ensure_deps(apps=True, updates=True):
        console.print("[yellow]Some dependencies could not be prepared. Health Check may be limited.[/]\n")

    console.print("\n[bold cyan]--- Health Check ---[/]")
    console.print(f"[grey]Log file: {LOG_FILE}[/]\n")

    layout = Layout()
    layout.split_column(Layout(name="progress", size=3), Layout(name="logs", ratio=1))

    logs: List[str] = []

    progress = Progress(
        SpinnerColumn(),
        BarColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    task = progress.add_task("Scanning system health…", total=100)

    layout["progress"].update(Panel(progress, title="Progress"))
    layout["logs"].update(Panel(Text("Starting…"), title="Live Log"))

    with Live(layout, refresh_per_second=14, console=console, screen=False):
        # Apps 0..40
        progress.update(task, description="Preparing winget app scan…")
        logs.append("Preparing winget app scan…")
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
        apps = _stream_winget_upgrades(logs, layout, progress, task_id=task, phase_start=0.0, phase_end=40.0)
        logs.append(f"App scan complete. {len(apps)} update(s) detected.")
        if len(logs) > 20: logs.pop(0)
        layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    # Windows updates removed: skip this phase to avoid PSWindowsUpdate dependency/hangs
    progress.update(task, description="Windows updates disabled — skipping…")
    logs.append("Windows updates disabled; skipping PowerShell scan.")
    if len(logs) > 20: logs.pop(0)
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
    # advance progress to end of the Windows phase
    progress.update(task, completed=80.0)
    os_items = []

    # Junk 80..100
    progress.update(task, description="Scanning junk files…")
    logs.append("Scanning junk files…")
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
    junk_size = calc_size(get_temp_paths())
    logs.append(f"Junk size detected: {human_bytes(junk_size)}")
    if len(logs) > 20: logs.pop(0)
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))
    progress.update(task, completed=100.0)
    logs.append("Scan complete.")
    layout["logs"].update(Panel(Text("\n".join(logs[-20:])), title="Live Log"))

    console.print("\n[bold cyan]Health Summary[/]")
    console.print(f"- Apps needing updates: [yellow]{len(apps)}[/]")
    console.print(f"- Windows updates available: [yellow]{len(os_items)}[/]")
    console.print(f"- Junk detected: [yellow]{human_bytes(junk_size)}[/]")

    choice = input("\nApply Fix All now? (Y/N): ").strip().lower()
    if choice != "y":
        console.print("[grey]No changes applied.[/]")
        return

    if apps:
        console.print("\n[bold green]Updating applications…[/]")
        winget_upgrade([a["Id"] for a in apps])

    if os_items:
        console.print("\n[bold green]Windows updates were detected but automatic installation is disabled.[/]")

    if junk_size > 0:
        console.print("\n[bold green]Cleaning junk…[/]")
        freed = clean_junk()
        console.print(f"Freed {human_bytes(freed)}")

    console.print("\n[bold green]Health Check complete![/]")
