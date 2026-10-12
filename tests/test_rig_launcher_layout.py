"""Check actual Tk widget allocation at normal and enlarged font scaling."""

import sys
from dataclasses import replace

import pytest

tk = pytest.importorskip("tkinter")


def _descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from _descendants(child)


@pytest.mark.parametrize("scaling", [1.0, 2.0])
def test_fresh_launcher_and_minimum_size_show_all_controls(scaling, tk_root):
    from tools.rig_launcher.preview import _NOOP_ACTIONS, demo_status
    from tools.rig_launcher.supervisor import ProbeResult
    from tools.rig_launcher.view import build_launcher_view

    root = tk.Toplevel(tk_root)
    try:
        root.withdraw()
        root.title("Game Point layout test")
        root.tk.call("tk", "scaling", scaling)
        view = build_launcher_view(
            root,
            actions=_NOOP_ACTIONS,
            status_path="status.json",
            on_toggle_simhub=lambda enabled: None,
        )
        view.mark_pending()
        view.fit_window()
        root.deiconify()
        root.update()
        status = replace(
            demo_status(),
            tablet=ProbeResult("tablet", True, "dash-connected", "browser_peers=1"),
            resilient=ProbeResult(
                "ac_session",
                False,
                "menu_config_required",
                "Set [NEW_UI] REPLACE_MAIN_MENU=0 in "
                r"C:\Users\driver\OneDrive\Documents\Assetto Corsa\cfg\extension\gui.ini",
            ),
        )
        view.update(status)
        for geometry in [None, "1x1"]:
            if geometry:
                root.geometry(geometry)
            root.update()
            left, top = root.winfo_rootx(), root.winfo_rooty()
            width, height = root.winfo_width(), root.winfo_height()
            controls = [w for w in _descendants(root) if isinstance(w, tk.Button)]
            labels = [w for w in _descendants(root) if isinstance(w, tk.Label)]
            assert len(controls) == 7
            assert any(w.cget("text") == "DASH-CONNECTED" for w in labels)
            assert any(w.cget("text") == "MENU_CONFIG_REQUIRED" for w in labels)
            for widget in controls + labels:
                assert widget.winfo_ismapped(), widget.cget("text")
                assert widget.winfo_width() >= widget.winfo_reqwidth(), (
                    f"{widget.cget('text')} min={root.minsize()} req={root.winfo_reqwidth()} "
                    f"width={width} max={root.maxsize()} wrap={widget.cget('wraplength')}"
                )
                x, y = widget.winfo_rootx() - left, widget.winfo_rooty() - top
                assert 0 <= x and x + widget.winfo_width() <= width, widget.cget("text")
                assert 0 <= y and y + widget.winfo_height() <= height, widget.cget("text")
        root.geometry(f"{width + 100}x{height + 100}")
        root.update()
        enlarged = root.winfo_width(), root.winfo_height()
        view.update(demo_status())
        root.update()
        assert (root.winfo_width(), root.winfo_height()) == enlarged
    finally:
        root.destroy()


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        if sys.platform == "win32":
            raise
        pytest.skip("Tk display unavailable")
    root.withdraw()
    yield root
    root.destroy()
