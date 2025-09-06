# CoreUpdateCLI

A no-nonsense Windows CLI to keep a machine healthy:

- **Apps**: scan & update with `winget`, uninstall apps.
- **Windows Update**: list and install pending updates.
- **Drivers**: list & install driver updates from Windows Update; list/rollback driver packages with `pnputil`.
- **Rollback**: uninstall a Windows KB with `wusa`.

> Built for Windows 10/11. Requires an **elevated** console.

## Why this design?

- Uses **first-party tooling** only (`winget`, PowerShell, `PSWindowsUpdate`, `pnputil`, `wusa`).  
- No brittle scraping. Everything is parsed from **JSON** or stable text.
- All subprocess calls pass **arg lists**, never concat raw user strings (mitigates injection).
- You always **choose** what to install or remove.

## Setup

1. Open **Windows Terminal** → **PowerShell** as *Administrator*.
2. Ensure `winget` is available (`winget --version`). Install *App Installer* from Microsoft Store if needed.
3. Run:

```powershell
python .\main.py --help
