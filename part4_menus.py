#!/usr/bin/env python3
# part4_menus.py — Interactive menus for CoreUpdateCLI with live logs

import os
from typing import List

from part1_bootstrap import console, log, LOG_FILE, tail_log, CONSENT_FILE
from part2_helpers import (
    run_with_live_output,
    ensure_deps,                               # NEW
    winget_list_upgrades, winget_upgrade_all, winget_uninstall_fuzzy,
    list_windows_updates, install_windows_updates,
    list_driver_updates, list_installed_drivers, rollback_driver, export_all_drivers,
)
from part3_health import health_check, clean_junk, human_bytes, get_temp_paths, calc_size

from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.live import Live

def pause():
    input("\nPress Enter to return to menu…")

# ---------------- Custom Clean ----------------

def menu_custom_clean():
    layout = Layout()
    layout.split_column(Layout(name="progress", size=3), Layout(name="logs", ratio=1))
    logs: List[str] = []

    progress = Progress(
        SpinnerColumn(), BarColumn(), TextColumn("{task.description}"), TimeElapsedColumn(),
        console=console, transient=False
    )
    task = progress.add_task("Custom Clean scan…", total=100)

    layout["progress"].update(Panel(progress, title="Progress"))
    layout["logs"].update(Panel(Text("Starting…"), title="Logs"))

    with Live(layout, refresh_per_second=12, console=console):
        logs.append("Scanning junk folders…")
        layout["logs"].update(Panel(Text("\n".join(logs[-12:])), title="Logs"))
        size = calc_size(get_temp_paths())
        logs.append(f"Detected {human_bytes(size)} junk")
        progress.advance(task, 70)
        layout["logs"].update(Panel(Text("\n".join(logs[-12:])), title="Logs"))

        progress.update(task, completed=100)
        logs.append("Scan complete.")
        layout["logs"].update(Panel(Text("\n".join(logs[-12:])), title="Logs"))

    console.print(f"\nJunk detected: [yellow]{human_bytes(size)}[/]")
    if input("Clean now? (Y/N): ").lower().startswith("y"):
        freed = clean_junk()
        console.print(f"[green]Cleaned {human_bytes(freed)}[/]")
    pause()

# ---------------- Performance Optimizer ----------------

def menu_performance_optimizer():
    console.print("\n[bold cyan]Performance Optimizer[/]")
    console.print("- Switch power plan quickly.\n")
    while True:
        console.print("1) Balanced plan")
        console.print("2) High Performance")
        console.print("3) Ultimate Performance (enable + set)")
        console.print("4) Back\n")
        c = input("Choose: ").strip()
        if c == "1":
            run_with_live_output(["powercfg","/setactive","381b4222-f694-41f0-9685-ff5bb260df2e"], "Power plan: Balanced")
        elif c == "2":
            run_with_live_output(["powercfg","/setactive","8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"], "Power plan: High performance")
        elif c == "3":
            run_with_live_output(
                ["powershell","-NoProfile","-Command","powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61"],
                "Enable Ultimate Performance"
            )
            run_with_live_output(["powercfg","/setactive","e9a42b02-d5df-448d-aa00-03f14749eb61"], "Power plan: Ultimate")
        else:
            break
    pause()

# ---------------- Driver Updater ----------------

def menu_driver_updater():
    # Self-heal: driver flows need PSWindowsUpdate
    if not ensure_deps(drivers=True):
        console.print("[red]Driver update functions unavailable (PSWindowsUpdate not prepared).[/]")
        pause()
        return

    console.print("\n[bold cyan]Driver Updater[/]")

    drv_updates = list_driver_updates()
    console.print(f"Driver updates available: [yellow]{len(drv_updates)}[/]")
    if drv_updates:
        for i, u in enumerate(drv_updates[:20], 1):
            console.print(f"[{i:02}] {u.title}")
        if input("\nInstall ALL driver updates now? (Y/N): ").lower().startswith("y"):
            ids = [u.update_id for u in drv_updates]
            install_windows_updates(ids)

    drivers = list_installed_drivers()
    console.print(f"\nInstalled drivers found: [yellow]{len(drivers)}[/]")
    for i, d in enumerate(drivers[:15], 1):
        console.print(f"[{i:02}] {d.provider} - {d.published_name}  v{d.version}")

    if input("\nRollback a driver by 'oemXX.inf'? (Y/N): ").lower().startswith("y"):
        pn = input("Enter published name (e.g., oem42.inf): ").strip()
        if pn:
            rollback_driver(pn)

    if input("\nExport all drivers to Desktop? (Y/N): ").lower().startswith("y"):
        target = os.path.join(os.path.expandvars("%USERPROFILE%"), "Desktop", "DriverBackup")
        export_all_drivers(target)
        console.print(f"[green]Drivers exported to {target}[/]")

    pause()

# ---------------- Tools ----------------

def menu_tools():
    while True:
        console.print("\n[bold cyan]Tools[/]")
        console.print("1. Update ALL applications")
        console.print("2. Uninstall application (fuzzy match or ID)")
        console.print("3. Rollback a Windows KB update")
        console.print("4. Create Restore Point")
        console.print("5. Back\n")
        c = input("Choose: ").strip()
        if c == "1":
            # apps need winget
            if ensure_deps(apps=True):
                winget_upgrade_all()
        elif c == "2":
            if ensure_deps(apps=True):
                query = input("Enter app name or ID to uninstall: ").strip()
                if query:
                    winget_uninstall_fuzzy(query)
        elif c == "3":
            kb = input("Enter KB number (digits only): ").strip()
            if kb and kb.isdigit():
                # no heavy deps needed; do a presence check then uninstall
                ps = f"Get-HotFix -Id KB{kb} -ErrorAction SilentlyContinue"
                rc, out = run_with_live_output(
                    ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps],
                    f"Check KB{kb}"
                )
                if "KB" in (out or ""):
                    run_with_live_output(["wusa.exe", "/uninstall", f"/kb:{kb}", "/quiet", "/norestart"], f"Rollback KB{kb}")
                else:
                    console.print(f"[grey]KB{kb} not found installed.[/]")
        elif c == "4":
            desc = input("Restore point description: ").strip() or "CoreUpdateCLI"
            rc, out = run_with_live_output(
                ["powershell","-NoProfile","-Command", f'Checkpoint-Computer -Description "{desc}" -RestorePointType "MODIFY_SETTINGS"'],
                "Creating Restore Point"
            )
            if rc != 0:
                console.print("[red]Failed to create restore point (System Restore may be disabled).[/]")
        elif c == "5":
            break
    pause()

# ---------------- Options ----------------

def menu_options():
    console.print("\n[bold cyan]Options[/]")
    console.print("1. Reset consent")
    console.print("2. Clear logs")
    console.print("3. Back\n")
    c = input("Choose: ").strip()
    if c == "1":
        try:
            os.remove(CONSENT_FILE); console.print("Consent reset. You'll be prompted next launch.")
        except Exception:
            console.print("Failed to reset consent file.")
    elif c == "2":
        try:
            open(LOG_FILE,"w").close(); console.print("Logs cleared.")
        except Exception:
            console.print("Failed to clear logs.")
    pause()

# ---------------- Diagnostics ----------------

def menu_diagnostics():
    console.print("\n[bold cyan]Diagnostics[/]")

    # winget quick test (self-heal if missing)
    rc, out = run_with_live_output(["winget", "--version"], "winget --version")
    if rc != 0:
        console.print("[red]winget not available. Attempting to bootstrap…[/]")
        ensure_deps(apps=True)  # triggers Store page if needed
    else:
        console.print(f"\nwinget: rc={rc}  out={(out or '').strip() or '-'}")

    # PSWindowsUpdate quick test (self-heal if missing)
    ps = "Get-Module -ListAvailable PSWindowsUpdate | Select-Object -First 1 | ForEach-Object {$_.Name + ' ' + $_.Version}"
    rc2, out2 = run_with_live_output(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps], "Check PSWindowsUpdate")
    if "PSWindowsUpdate" not in (out2 or ""):
        console.print("[red]PSWindowsUpdate not found. Installing…[/]")
        ensure_deps(updates=True)
    else:
        console.print(f"PSWindowsUpdate: {(out2 or '').strip()}")

    console.print(f"\nLog file: {LOG_FILE}\n")
    console.print(tail_log(80))
    pause()
