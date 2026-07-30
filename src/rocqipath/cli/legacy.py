"""Historical interactive menu backed by the unified command modules."""

from __future__ import annotations

from rocqipath.cli.commands.align import run_interactive as _align
from rocqipath.cli.commands.extract import (
    run_tma_interactive as _extract_tma,
    run_wsi_interactive as _extract_wsi,
)
from rocqipath.cli.commands.stain import run_interactive as _stain

_SEP = "=" * 72
_DISPATCH = {"1": _align, "2": _extract_wsi, "3": _extract_tma, "4": _stain}


def _print_header() -> None:
    """Print the historical menu and the installed RocqiPath version."""
    import rocqipath

    print("\n" + _SEP)
    print(f"  rocqipath  |  Author: Darshil Gajjar  |  Version: v{rocqipath.__version__}")
    print(_SEP)
    print("  Main Menu:")
    print("    1.  Alignment Pipeline")
    print("    2.  Tissue Extraction — WSI")
    print("    3.  Tissue Extraction — TMA/core")
    print("    4.  Stain Normalization")
    print("    5.  Exit")
    print()


def main_menu() -> None:
    """Run the interactive menu loop until Exit is selected."""
    while True:
        _print_header()
        choice = input("  Enter choice (1-5): ").strip()
        if choice == "5":
            print("\n  Exiting RocqiPath. Goodbye.\n")
            break
        if choice in _DISPATCH:
            try:
                _DISPATCH[choice]()
            except SystemExit:
                pass
            except KeyboardInterrupt:
                print("\n  (Interrupted - returning to menu)")
        else:
            print(f"  Invalid choice '{choice}'. Please enter 1, 2, 3, 4, or 5.")
