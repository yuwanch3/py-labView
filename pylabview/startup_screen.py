from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable


class StartupScreen:
    """Splash/loading screen followed by application mode selection."""

    def __init__(
        self,
        root: tk.Tk,
        logo_path: Path,
        on_mode_selected: Callable[[str], None],
    ) -> None:
        self.root = root
        self.logo_path = logo_path
        self.on_mode_selected = on_mode_selected

        self.window = tk.Toplevel(root)
        self.window.title("GMJ Global Energy")
        self.window.geometry("720x460")
        self.window.resizable(False, False)
        self.window.configure(background="#f4f5f7")
        self.window.protocol("WM_DELETE_WINDOW", self.root.destroy)

        self._logo_image: tk.PhotoImage | None = None
        self._progress_value = 0

        self._center_window()
        self._show_splash()

    def _center_window(self) -> None:
        self.window.update_idletasks()
        width, height = 720, 460
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = max(0, (self.window.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _clear(self) -> None:
        for child in self.window.winfo_children():
            child.destroy()

    def _load_logo(self) -> tk.PhotoImage | None:
        if not self.logo_path.exists():
            return None
        try:
            image = tk.PhotoImage(file=str(self.logo_path))
        except tk.TclError:
            return None

        max_width, max_height = 360, 150
        scale = max(
            1,
            (image.width() + max_width - 1) // max_width,
            (image.height() + max_height - 1) // max_height,
        )
        if scale > 1:
            image = image.subsample(scale, scale)
        return image

    def _show_splash(self) -> None:
        self._clear()

        frame = tk.Frame(self.window, background="#f4f5f7")
        frame.pack(fill="both", expand=True)

        logo_holder = tk.Frame(
            frame,
            background="#f4f5f7",
            height=180,
        )
        logo_holder.pack(fill="x", pady=(65, 0))
        logo_holder.pack_propagate(False)

        self._logo_image = self._load_logo()

        if self._logo_image is not None:
            tk.Label(
                logo_holder,
                image=self._logo_image,
                background="#f4f5f7",
                borderwidth=0,
            ).pack(expand=True)
        else:
            tk.Label(
                logo_holder,
                text="GMJ GLOBAL ENERGY",
                background="#f4f5f7",
                foreground="#26364a",
                font=("TkDefaultFont", 20, "bold"),
            ).pack(expand=True)

        tk.Label(
            frame,
            text="Initializing PyLabView Studio...",
            background="#f4f5f7",
            foreground="#4b5563",
            font=("TkDefaultFont", 10),
        ).pack(pady=(20, 8))

        self.progress = ttk.Progressbar(
            frame,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            length=420,
        )
        self.progress.pack()

        self._progress_value = 0
        self._advance_progress()

    def _advance_progress(self) -> None:
        if not self.window.winfo_exists():
            return

        self._progress_value += 4
        self.progress["value"] = min(self._progress_value, 100)

        if self._progress_value >= 100:
            self.window.after(180, self._show_mode_selection)
            return

        self.window.after(45, self._advance_progress)

    def _show_mode_selection(self) -> None:
        self._clear()

        frame = tk.Frame(self.window, background="#f4f5f7")
        frame.pack(fill="both", expand=True, padx=90, pady=55)

        tk.Label(
            frame,
            text="Select Operating Mode",
            background="#f4f5f7",
            foreground="#1f2937",
            font=("TkDefaultFont", 18, "bold"),
        ).pack(pady=(20, 8))

        tk.Label(
            frame,
            text="Choose how you want to operate the spinning-drop system.",
            background="#f4f5f7",
            foreground="#667085",
            font=("TkDefaultFont", 10),
        ).pack(pady=(0, 32))

        ttk.Button(
            frame,
            text="Standard Mode",
            command=lambda: self._select_mode("standard"),
        ).pack(fill="x", ipady=12, pady=(0, 16))

        tk.Label(
            frame,
            text="Automatic 1000 -> 6000 RPM sequence using the existing system.",
            background="#f4f5f7",
            foreground="#667085",
            font=("TkDefaultFont", 9),
        ).pack(pady=(0, 22))

        ttk.Button(
            frame,
            text="Manual RPM Mode",
            command=lambda: self._select_mode("manual"),
        ).pack(fill="x", ipady=12, pady=(0, 16))

        tk.Label(
            frame,
            text="Manual target-RPM workspace. RPM logic will be added in the next stage.",
            background="#f4f5f7",
            foreground="#667085",
            font=("TkDefaultFont", 9),
        ).pack()

    def _select_mode(self, mode: str) -> None:
        if mode not in ("standard", "manual"):
            return
        self.window.destroy()
        self.on_mode_selected(mode)
