"""Run from Cinema 4D Script Manager or the workspace AI plugin center.

Author: 与可 | YUKE (DeepLeap)
Repository: https://github.com/DeepLeap/scimol-c4d
"""

__author__ = "与可 | YUKE"
__brand__ = "YUKE · DeepLeap"
__version__ = "1.2.0"

import builtins
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_RELOAD_ORDER = (
    "records", "search_index", "resolve_cache", "backend", "appearance_scale",
    "hydrogen_layout", "display_geometry", "library", "usage", "c4d_builder",
    "native_ui", "atom_selector", "resource_browser", "floating_windows",
    "browser_layout", "ui", "browser_ui",
)


def _reload_loaded_submodules():
    for name in _RELOAD_ORDER:
        module_name = "scimol_c4d." + name
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])


def run(doc=None):
    existing = getattr(builtins, "_scimol_native_dialog_v1", None)
    if existing is not None and existing.IsOpen():
        return True
    _reload_loaded_submodules()
    from scimol_c4d import ui
    return ui.run(doc)


if __name__ == "__main__":
    run()
