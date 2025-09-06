#!/usr/bin/env python3
# part5_main.py — Main menu loop for CoreUpdateCLI

import sys, os
from datetime import datetime

from part1_bootstrap import (
    request_permissions_or_exit,
    ensure_env_bootstrap,
    ensure_admin,
    console,
)
from part3_health import health_check
from part4_menus import (
    menu_custom_clean,
    menu_performance_optimizer,
    menu_driver_updater,
    menu_tools,
    menu_options,
    menu_diagnostics,
)

APP_VERSION = "v1.0"
BUILD_DATE = datetime.now().strftime("%Y-%m-%d")

def clear_screen():
    """Cross-platform console clear."""
    os.system("cls" if os.name == "nt" else "clear")

def show_banner(version: str, build_date: str):
    clear_screen()
    console.print("[bold blue]=== Core Update CLI {} ({}) ===[/]\n".format(version, build_date))

def interactive_menu(version: str, build_date: str):
    while True:
        show_banner(version, build_date)
        console.print("1. Health Check")
        console.print("2. Custom Clean")
        console.print("3. Performance Optimizer")
        console.print("4. Driver Updater")
        console.print("5. Tools")
        console.print("6. Options")
        console.print("7. Diagnostics")
        console.print("8. Exit\n")

        choice = input("Choose an option (1-8): ").strip()
        console.print()  # spacer

        if choice == "1":
            health_check()  # already handles its own flow
        elif choice == "2":
            menu_custom_clean()
        elif choice == "3":
            menu_performance_optimizer()
        elif choice == "4":
            menu_driver_updater()
        elif choice == "5":
            menu_tools()
        elif choice == "6":
            menu_options()
        elif choice == "7":
            menu_diagnostics()
        elif choice == "8":
            console.print("Goodbye!")
            sys.exit(0)
        else:
            console.print("[yellow]Invalid choice.[/]\n")

def main(version: str = APP_VERSION, build_date: str = BUILD_DATE):
    # Pre-menu bootstrapping
    request_permissions_or_exit()
    ensure_env_bootstrap()
    ensure_admin()

    show_banner(version, build_date)
    # Don't enter interactive loop in non-interactive environments (tests/CI)
    if sys.stdin and sys.stdin.isatty():
        interactive_menu(version, build_date)
    else:
        # In tests, just show the banner and return
        return

if __name__ == "__main__":
    main()
