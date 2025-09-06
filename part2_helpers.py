#!/usr/bin/env python3
# part2_helpers.py — subprocess + package manager helpers for CoreUpdateCLI

import os, sys, subprocess, re, json, shutil
from dataclasses import dataclass
from typing import List, Tuple, Optional

from part0_platform import OS_NAME, has_cap
from part1_bootstrap import console, log, LOG_FILE
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.layout import Layout



# =============================================================================
# Subprocess runner with live output (seeded UI, scalable progress)
# =============================================================================

def run_with_live_output(cmd: List[str], title: str, soft_total: int = 100) -> Tuple[int, str]:
    """
    Run a command with a live progress bar + scrolling log panel.
    - soft_total: logical 'total' for the bar; we advance by 1 per line safely.
    Returns (exit_code, combined_output_string).
    """
    layout = Layout()
    layout.split_column(Layout(name="progress", size=3), Layout(name="logs", ratio=1))

    logs: List[str] = []
    combined: List[str] = []

    progress = Progress(
        SpinnerColumn(),
        BarColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    task = progress.add_task(title, total=soft_total)

    layout["progress"].update(Panel(progress, title="Progress"))
    layout["logs"].update(Panel(Text("Starting…"), title="Live Log"))

    # Seed the live log with the task title so users immediately see what is being prepared
    logs.append(title)
    if len(logs) > 40:
        logs = logs[-40:]
    layout["logs"].update(Panel(Text("\n".join(logs)), title="Live Log"))
    # Ensure the progress task description is current
    try:
        progress.update(task, description=title)
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        msg = f"Command not found: {cmd[0]}"
        console.print(f"[red]{msg}[/]")
        log(msg)
        return 127, msg

    tick = 0
    with Live(layout, refresh_per_second=12, console=console, screen=False):
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                s = line.rstrip()
                combined.append(s)
                logs.append(s)
                if len(logs) > 40:
                    logs = logs[-40:]
                tick += 1
                if tick <= soft_total:
                    progress.advance(task, 1)
                layout["logs"].update(Panel(Text("\n".join(logs)), title="Live Log"))

        proc.wait()
        progress.update(task, completed=soft_total)
        layout["progress"].update(Panel(progress, title="Progress"))

    output = "\n".join(combined)
    log(f"[run] {cmd} -> rc={proc.returncode}")
    if output.strip():
        log(output[:8000])
    return proc.returncode or 0, output

# =============================================================================
# Winget helpers
# =============================================================================

@dataclass
class WingetApp:
    id: str
    name: str
    version: str
    available: str

def resolve_winget_path() -> str:
    """
    Prefer PATH resolution (portable or user installs) then known locations.
    """
    which = shutil.which("winget")
    if which:
        return which
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Apps\winget.exe"),
        r"C:\Windows\System32\winget.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "winget"

def ensure_winget_ready() -> None:
    exe = resolve_winget_path()
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True)
        if r.returncode != 0:
            raise FileNotFoundError
    except Exception:
        console.print("[yellow]App Installer (winget) is not available. Opening Store page…[/]")
        subprocess.Popen(["powershell", "Start-Process", "ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1"])
        raise RuntimeError("Install 'App Installer' from Microsoft Store, then re-run.")
    subprocess.run([exe, "source", "update"], capture_output=True, text=True)

def winget_list_upgrades() -> List[WingetApp]:
    try:
        ensure_winget_ready()
    except RuntimeError as e:
        console.print(f"[yellow]{e}[/]")
        return []
    exe = resolve_winget_path()
    help_out = subprocess.run([exe, "upgrade", "-?"], capture_output=True, text=True).stdout or ""
    if "--output" in help_out:
        res = subprocess.run([exe, "upgrade", "--include-unknown", "--output", "json"],
                             capture_output=True, text=True)
        try:
            items = json.loads(res.stdout)
            rows = []
            for it in items:
                pid = it.get("Id") or it.get("PackageIdentifier")
                name = it.get("Name", "")
                ver = it.get("Version") or it.get("InstalledVersion") or ""
                avail = it.get("Available") or it.get("AvailableVersion") or ""
                if pid and avail:
                    rows.append(WingetApp(pid, name, ver, avail))
            if rows:
                return rows
        except Exception:
            pass
    # table parse fallback
    res = subprocess.run([exe, "upgrade", "--include-unknown"], capture_output=True, text=True)
    rows = []
    for line in res.stdout.splitlines():
        if re.match(r"^\s*(Name|---)", line):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 4:
            name, pid, ver, avail = parts[:4]
            if pid and avail and not pid.lower().startswith("no "):
                rows.append(WingetApp(pid, name, ver, avail))
    return rows

def winget_list_installed() -> List[WingetApp]:
    try:
        ensure_winget_ready()
    except RuntimeError:
        return []
    exe = resolve_winget_path()
    res = subprocess.run([exe, "list"], capture_output=True, text=True)
    rows: List[WingetApp] = []
    for line in res.stdout.splitlines():
        if re.match(r"^\s*(Name|---)", line):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3:
            name, pid, ver = parts[:3]
            if pid and not pid.lower().startswith("no "):
                rows.append(WingetApp(pid, name, ver, ""))
    return rows

def winget_upgrade_all():
    apps = winget_list_upgrades()
    if not apps:
        console.print("[grey]No upgradable apps found.[/]")
        return
    ids = [a.id for a in apps]
    winget_upgrade(ids)

def winget_upgrade(ids: List[str]):
    exe = resolve_winget_path()
    for pid in ids:
        run_with_live_output(
            [exe, "upgrade", "--id", pid, "-h",
             "--disable-interactivity",
             "--accept-package-agreements",
             "--accept-source-agreements"],
            f"Updating {pid}",
            soft_total=120
        )

def winget_uninstall(pid: str):
    exe = resolve_winget_path()
    run_with_live_output(
        [exe, "uninstall", "--id", pid, "--silent", "--disable-interactivity"],
        f"Uninstall {pid}",
        soft_total=80
    )

def winget_uninstall_fuzzy(query: str) -> Optional[str]:
    apps = winget_list_installed()
    if not apps:
        console.print("[grey]No installed apps retrieved.[/]")
        return None
    for a in apps:
        if a.id.lower() == query.lower():
            winget_uninstall(a.id)
            return a.id
    matches = [a for a in apps if query.lower() in a.name.lower()]
    if len(matches) == 1:
        winget_uninstall(matches[0].id)
        return matches[0].id
    elif len(matches) > 1:
        console.print("[yellow]Multiple matches:[/]")
        for i, m in enumerate(matches, 1):
            console.print(f"{i:02}. {m.name}  [{m.id}]  v{m.version or '-'}")
        sel = input("Pick a number to uninstall (or blank to cancel): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(matches):
            winget_uninstall(matches[int(sel)-1].id)
            return matches[int(sel)-1].id
    else:
        console.print("[grey]No match for that name/ID.[/]")
    return None

# ---------------- macOS (brew) helpers ----------------

def brew_list_upgrades() -> List[WingetApp]:
    """Return outdated brew packages as WingetApp-like rows (id=name)."""
    r = subprocess.run(["brew","outdated","--json=v2"], capture_output=True, text=True)
    if r.returncode != 0:
        console.print("[red]Failed to query brew outdated.[/]")
        return []
    try:
        data = json.loads(r.stdout or "{}")
    except Exception:
        data = {}
    rows: List[WingetApp] = []
    # formulas
    for f in (data.get("formulae") or []):
        name = f.get("name")
        current = (f.get("installed_versions") or [""])[-1]
        latest = f.get("current_version") or ""
        if name and latest and current and current != latest:
            rows.append(WingetApp(id=name, name=name, version=current, available=latest))
    # casks
    for c in (data.get("casks") or []):
        name = c.get("name")
        current = c.get("installed_versions") or []
        current_v = current[-1] if current else ""
        latest = c.get("current_version") or ""
        if name and latest and current_v and current_v != latest:
            rows.append(WingetApp(id=name, name=name, version=current_v, available=latest))
    return rows

def brew_upgrade(ids: List[str]):
    # upgrade formulae/casks by name; brew will pick correct type
    for pkg in ids:
        run_with_live_output(["brew","upgrade",pkg], f"Updating {pkg}", soft_total=80)

def brew_upgrade_all():
    run_with_live_output(["brew","upgrade"], "Updating all brew packages", soft_total=120)

def brew_list_installed() -> List[WingetApp]:
    r = subprocess.run(["brew","list","--versions"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    rows: List[WingetApp] = []
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split()
        if not parts: continue
        name, versions = parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""
        rows.append(WingetApp(id=name, name=name, version=versions, available=""))
    return rows

def brew_uninstall_fuzzy(query: str) -> Optional[str]:
    apps = brew_list_installed()
    if not apps:
        console.print("[grey]No installed brew packages retrieved.[/]")
        return None
    for a in apps:
        if a.id.lower() == query.lower() or a.name.lower() == query.lower():
            run_with_live_output(["brew","uninstall",a.id], f"Uninstall {a.id}", soft_total=60)
            return a.id
    matches = [a for a in apps if query.lower() in a.name.lower()]
    if len(matches) == 1:
        run_with_live_output(["brew","uninstall",matches[0].id], f"Uninstall {matches[0].id}", soft_total=60)
        return matches[0].id
    elif len(matches) > 1:
        console.print("[yellow]Multiple matches:[/]")
        for i, m in enumerate(matches, 1):
            console.print(f"{i:02}. {m.name}  [{m.id}]  v{m.version or '-'}")
        sel = input("Pick a number to uninstall (or blank to cancel): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(matches):
            pkg = matches[int(sel)-1].id
            run_with_live_output(["brew","uninstall",pkg], f"Uninstall {pkg}", soft_total=60)
            return pkg
    else:
        console.print("[grey]No match for that name/ID.[/]")
    return None


# =============================================================================
# Windows Update helpers (PSWindowsUpdate)
# =============================================================================

def ensure_pswindowsupdate_installed() -> bool:
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$repo = Get-PSRepository -Name 'PSGallery' -ErrorAction SilentlyContinue
if (-not $repo) { Register-PSRepository -Default | Out-Null }
$prov = Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue
if (-not $prov) { Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null }
$mod = Get-Module -ListAvailable PSWindowsUpdate | Select-Object -First 1
if (-not $mod) { Install-Module -Name PSWindowsUpdate -Scope CurrentUser -Force -AllowClobber -Repository PSGallery | Out-Null }
Import-Module PSWindowsUpdate -Force
'OK'
"""
    rc, out = run_with_live_output(
        ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps],
        "Preparing PSWindowsUpdate",
        soft_total=40
    )
    return (rc == 0) and ("OK" in out)

@dataclass
class WinUpdate:
    title: str
    kb: Optional[str]
    update_id: str
    categories: List[str]

def _ps_get_updates(include_drivers: bool) -> List[WinUpdate]:
    if not ensure_pswindowsupdate_installed():
        return []
    cat = "-Category 'Drivers'" if include_drivers else ""
    ps = rf"""
Import-Module PSWindowsUpdate
$u = Get-WindowsUpdate -MicrosoftUpdate {cat} -IgnoreReboot -AcceptAll
$rows = @()
foreach ($x in $u) {{
  $kb = $null
  if ($x.KB) {{ $kb = ($x.KB | Select-Object -First 1) }}
  elseif ($x.Title -match 'KB\d{{5,7}}') {{ $kb = $Matches[0] }}
  $rows += [PSCustomObject]@{{
    Title = $x.Title
    KB    = $kb
    UpdateId = $x.UpdateID
    Categories = @($x.Categories | ForEach-Object {{ $_.Name }})
  }}
}}
$rows | ConvertTo-Json -Depth 4
"""
    rc, out = run_with_live_output(
        ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps],
        "Scanning Windows Updates",
        soft_total=80
    )
    if rc != 0 or not out.strip():
        return []
    try:
        items = json.loads(out)
        if isinstance(items, dict):
            items = [items]
    except Exception:
        return []
    ups: List[WinUpdate] = []
    for it in items:
        ups.append(WinUpdate(it.get("Title",""), it.get("KB"), it.get("UpdateId",""),
                             list(it.get("Categories",[]) or [])))
    return ups

def list_windows_updates() -> List[WinUpdate]:
    return _ps_get_updates(include_drivers=False)

def list_driver_updates() -> List[WinUpdate]:
    return _ps_get_updates(include_drivers=True)

def install_windows_updates(update_ids: List[str]):
    """
    Install specific update IDs. Uses a proper PS array so commas/spaces are safe.
    """
    if not update_ids:
        return
    if not ensure_pswindowsupdate_installed():
        return
    ids_literal = "@(" + ",".join("'" + i.replace("'", "''") + "'" for i in update_ids) + ")"
    ps = f"""
Import-Module PSWindowsUpdate
Install-WindowsUpdate -MicrosoftUpdate -UpdateID {ids_literal} -AcceptAll -IgnoreReboot -AutoReboot:$false -Verbose:$false
"""
    run_with_live_output(
        ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command", ps],
        "Installing Windows Updates",
        soft_total=120
    )

# =============================================================================
# Driver helpers (pnputil)
# =============================================================================

@dataclass
class DriverPackage:
    published_name: str
    provider: str
    version: str
    date: str

def list_installed_drivers() -> List[DriverPackage]:
    res = subprocess.run(["pnputil", "/enum-drivers"], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        console.print("[red]pnputil failed to enumerate drivers[/]")
        return []
    blocks = re.split(r"\r?\n\r?\n", res.stdout.strip())
    pkgs = []
    for b in blocks:
        d = {}
        for line in b.splitlines():
            lo = line.lower()
            if lo.startswith("published name"):
                d["published_name"] = line.split(":",1)[1].strip()
            elif lo.startswith("driver package provider"):
                d["provider"] = line.split(":",1)[1].strip()
            elif lo.startswith("driver date and version"):
                tail = line.split(":",1)[1].strip()
                parts = tail.split()
                if len(parts) >= 2:
                    d["date"], d["version"] = parts[0], " ".join(parts[1:])
        if all(k in d for k in ("published_name","provider","version","date")):
            pkgs.append(DriverPackage(**d))
    return pkgs

def rollback_driver(published_name: str):
    run_with_live_output(
        ["pnputil", "/delete-driver", published_name, "/uninstall", "/force"],
        f"Rollback {published_name}",
        soft_total=60
    )

def export_all_drivers(target_dir: str):
    os.makedirs(target_dir, exist_ok=True)
    run_with_live_output(
        ["pnputil", "/export-driver", "*", target_dir],
        f"Exporting drivers → {target_dir}",
        soft_total=100
    )

# =============================================================================
# Global dependency guard
# =============================================================================

def ensure_deps(*, apps: bool = False, updates: bool = False, drivers: bool = False) -> bool:
    ok = True
    if apps:
        if OS_NAME == "windows":
            try:
                ensure_winget_ready()
            except Exception as e:
                console.print(f"[red]winget is not available: {e}[/]")
                ok = False
        elif OS_NAME == "darwin":
            # brew check
            r = subprocess.run(["brew","--version"], capture_output=True, text=True)
            if r.returncode != 0:
                console.print("[red]Homebrew not found. Install from https://brew.sh/[/]")
                ok = False
        else:
            console.print("[yellow]Package updates unsupported on this Linux configuration (add apt/dnf support later).[/]")
            ok = False
    if updates or drivers:
        if OS_NAME != "windows":
            console.print("[yellow]Windows/Driver updates are only available on Windows.[/]")
            ok = False
        else:
            if not ensure_pswindowsupdate_installed():
                console.print("[red]PSWindowsUpdate could not be prepared.[/]")
                ok = False
    return ok
