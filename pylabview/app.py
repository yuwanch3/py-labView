
import json
import math
import time
import zipfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from xml.sax.saxutils import escape
from queue import Empty, Queue
from threading import Thread
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from . import __version__
from .canvas_editor import DiagramCanvas
from .front_panel import PanelDesigner
from .model import (
    ConnectorTerminal,
    Graph,
    NODE_DEFINITIONS,
    Node,
    Project,
    clone_structure_properties,
    delete_owned_structure_diagrams,
    project_snapshot,
    restore_project_snapshot,
    _normalized_panel,
)
from .persistence import load_project, save_project
from .typesystem import DATA_TYPES, compatible, editor_value_text
from .runtime import DataflowRuntime
from .execution import RunController
from .plugins import DEFAULT_PLUGIN_REGISTRY
from .startup_screen import StartupScreen
from .paths import (
    bundled_assets_dir,
    bundled_examples_dir,
    copy_default_examples,
    ensure_user_directories,
    session_dir,
    session_info_path,
    session_analysis_dir,
    session_analysis_rpm_dir,
    session_measurements_dir,
    session_reference_dir,
    session_stages_dir,
)


class StudioApp(tk.Tk):

    def __init__(self) -> None:
        super().__init__()

        self._set_app_icon()

        ensure_user_directories()
        copy_default_examples()

        self.title("PyLabView Studio")
        self.geometry("1240x780")
        self.minsize(900, 600)

        self.project = Project()

        self.current_vi_id = (
            self.project.main_vi
        )

        self.graph = (
            self.project.main.graph
        )

        self.path: Path | None = None

        self.dirty = False

        self.undo_stack: list[
            dict[str, Any]
        ] = []

        self.redo_stack: list[
            dict[str, Any]
        ] = []

        self.clipboard_node: (
            dict[str, Any] | None
        ) = None

        self.runtime = (
            DataflowRuntime()
        )

        DEFAULT_PLUGIN_REGISTRY.discover()

        self.controller = (
            RunController(
                self.runtime
            )
        )

        self.continuous = False

        self.front_panel: (
            PanelDesigner | None
        ) = None

        self.breakpoints: set[str] = set()
        self.probes: set[str] = set()

        self.current_diagram_id: (
            str | None
        ) = None

        self.property_vars: dict[
            str,
            tk.StringVar
        ] = {}

        self._closing = False

        # One Excel file per spinning-drop measurement run.
        self._measurement_run_active = False
        self._measurement_exported = False
        self._last_motor_control = False
        self._measurement_run_counter = 0

        # Capture Reference momentary reset:
        # wait until one runtime result has actually processed the
        # True trigger before returning the control to False.
        self._capture_reference_reset_pending = False

        # Global STOP momentary reset:
        # keep the Front Panel STOP indicator active until the
        # RunController worker has actually finished shutting down.
        self._global_stop_reset_pending = False

        # Visual-only hold for the Front Panel Global STOP indicator.
        # This NEVER delays the actual motor/runtime stop. It only keeps
        # the red indicator visible long enough for the operator to see it.
        self._global_stop_indicator_started_at = 0.0
        self._global_stop_indicator_min_visible_s = 0.120

        # Gradual Stop toolbar state.
        # The motor ramp-down itself is performed entirely by Arduino.
        self._gradual_stop_in_progress = False
        self._gradual_stop_request_key = "spinning-drop-gradual-stop-requested"
        self._gradual_stop_complete_key = "spinning-drop-gradual-stop-complete"

        # Pre-run readiness is intentionally UI/runtime-derived only.
        # It never opens camera or serial resources by itself.
        self._pre_run_camera_ready = False
        self._pre_run_calibration_ready = False

        # Hardware status dashboard state. This is display-only and reuses
        # existing runtime/front-panel information; it never opens hardware.
        self._hardware_camera_connected = False
        self._hardware_arduino_connected = False

        # ========================================================
        # RUNTIME UI REFRESH CONTROL
        # ========================================================

        # Hanya result terbaru yang akan digambar.
        #
        # Jika runtime menghasilkan beberapa result sebelum Tkinter
        # sempat menggambar, result lama otomatis dibuang.
        self._latest_runtime_result: Any = None
        self._runtime_poll_after_id: str | None = None

        # Waktu terakhir Front Panel digambar.
        self._last_runtime_ui_update = 0.0

        # Maksimum update Front Panel:
        #
        # 0.20 detik = sekitar 5 FPS.
        #
        # Untuk spinning-drop ini cukup untuk tahap stabilisasi.
        # Nanti kalau sudah lancar bisa dinaikkan menjadi 0.10
        # untuk sekitar 10 FPS.
        self._runtime_ui_interval = 0.060

        self.operating_mode: str | None = None
        self._startup_screen: StartupScreen | None = None
        self._mode_switch_in_progress = False

        # One application launch / selected operating mode = one session.
        # paths.py owns path construction; app.py owns this lifecycle.
        self.session_root: Path | None = None
        self.session_id: str | None = None
        self.session_started_at: str | None = None

        # Analysis PNG optimization:
        # freeze lightweight Front Panel data on the UI thread, then render
        # and write PNG files in one background worker so runtime/UI refresh
        # is not blocked by GDI drawing and PNG compression.
        self._analysis_snapshot_jobs: Queue[
            tuple[
                dict[str, Any],
                Path,
            ]
        ] = Queue()

        self._analysis_snapshot_worker = Thread(
            target=self._analysis_snapshot_worker_loop,
            name="pylabview-analysis-snapshot",
            daemon=True,
        )

        self._analysis_snapshot_worker.start()

        # Display-only stage sample override.
        # Calibration/reference data inside the runtime graph remains frozen.
        self._stage_display_override_active = False

        self._build_style()
        self.withdraw()

        self.protocol(
            "WM_DELETE_WINDOW",
            self.close_app,
        )

        self._startup_screen = StartupScreen(
            self,
            self._startup_logo_path(),
            self._complete_startup,
        )

    # ============================================================
    # APPLICATION ICON
    # ============================================================

    def _set_app_icon(self) -> None:
        """Apply the GMJ icon to the root window and future Tk windows."""
        icon_path = (
            bundled_assets_dir()
            / "gmj-icon.png"
        )

        if not icon_path.exists():
            return

        try:
            # Keep a reference for the lifetime of the Tk application.
            self._app_icon = tk.PhotoImage(
                file=str(icon_path)
            )

            # default=True also applies this icon to future Toplevel windows,
            # including the operating-mode selector.
            self.iconphoto(
                True,
                self._app_icon,
            )

        except tk.TclError:
            # Icon failure must never prevent the application from starting.
            self._app_icon = None

    # ============================================================
    # STARTUP / MODE SELECTION
    # ============================================================

    @staticmethod
    def _startup_logo_path() -> Path:
        return (
            bundled_assets_dir()
            / "gmj-logo.png"
        )

    @staticmethod
    def _startup_project_path(
        mode: str,
    ) -> Path:

        filename = (
            "spinning_drop_ift.json"
            if mode == "standard"
            else "spinning_drop_manual_ift.json"
        )

        return (
            bundled_examples_dir()
            / filename
        )

    def _load_startup_project(
        self,
        mode: str,
    ) -> None:

        path = self._startup_project_path(
            mode
        )

        if not path.exists():

            raise FileNotFoundError(
                f"Startup project not found: {path}"
            )

        project = load_project(
            path
        )

        self.path = path
        self.undo_stack.clear()
        self.redo_stack.clear()

        self.project = project
        self.current_vi_id = project.main_vi
        self.graph = project.main.graph

        self.dirty = bool(
            project.migration_report
        )

    def _create_session(
        self,
        mode: str,
    ) -> None:
        """
        Create exactly one writable session folder for this app launch.

        This stage only creates the session structure and basic metadata.
        Existing capture/export workflows are intentionally NOT redirected
        yet.
        """

        now = datetime.now()

        mode_label = (
            "Standard"
            if mode == "standard"
            else "Manual"
        )

        session_name = (
            "Session_"
            + now.strftime(
                "%Y%m%d_%H%M%S"
            )
            + "_"
            + mode_label
        )

        root = session_dir(
            session_name
        )

        # A session must be unique to this application launch.
        root.mkdir(
            parents=True,
            exist_ok=False,
        )

        # Create only the structural folders. Individual RPM folders
        # are intentionally created later on demand.
        session_reference_dir(
            root
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

        session_stages_dir(
            root
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

        session_analysis_dir(
            root
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

        session_measurements_dir(
            root
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

        started_at = now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        metadata = {
            "session_id": session_name,
            "started_at": started_at,
            "mode": mode_label,
            "app_version": __version__,
        }

        session_info_path(
            root
        ).write_text(
            json.dumps(
                metadata,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        self.session_root = root
        self.session_id = session_name
        self.session_started_at = started_at

        # Expose the active application-owned session path to runtime
        # handlers without changing graph controls or redirecting any
        # existing output yet. spinning_drop.py will consume this in the
        # next stage.
        self.runtime.gmj_session_root = root
        self.runtime.gmj_analysis_capture_requests = []

    def _complete_startup(self, mode: str) -> None:
        self.operating_mode = mode
        self._startup_screen = None

        try:

            self._load_startup_project(
                mode
            )

        except (
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:

            messagebox.showerror(
                "Startup project failed",
                str(exc),
                parent=self,
            )

            self.destroy()
            return

        try:

            self._create_session(
                mode
            )

        except OSError as exc:

            messagebox.showerror(
                "Session setup failed",
                str(exc),
                parent=self,
            )

            self.destroy()
            return

        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self._update_title()

        if mode == "standard":
            self.status_var.set(
                "Standard Mode ready"
            )
        else:
            self.status_var.set(
                "Manual RPM Mode ready"
            )

        self.deiconify()
        self.lift()
        self.focus_force()

        # Ask after the main window has been laid out so the Panedwindow
        # sash positions can be moved safely if the operator chooses Yes.
        self.after(
            80,
            self._ask_collapse_workspace_panels,
        )

        self._mode_switch_in_progress = False

        self._runtime_poll_after_id = self.after(
            30,
            self._poll_runtime,
        )

    def change_mode(self) -> None:
        """Safely stop the active workspace and return to mode selection."""

        if self._mode_switch_in_progress:
            return

        if self.operating_mode not in (
            "standard",
            "manual",
        ):
            return

        if not messagebox.askyesno(
            "Ganti Mode",
            (
                "Ganti operating mode?\n\n"
                "Motor, camera, serial connection, dan runtime aktif "
                "akan dihentikan terlebih dahulu. Workspace mode saat ini "
                "akan di-reset sebelum mode baru dibuka."
            ),
            parent=self,
        ):
            return

        self._mode_switch_in_progress = True

        if self._runtime_poll_after_id is not None:
            try:
                self.after_cancel(
                    self._runtime_poll_after_id
                )
            except tk.TclError:
                pass
            self._runtime_poll_after_id = None

        # Reuse the existing hard/global STOP path exactly as-is:
        # Motor=False is pushed first, Arduino receives the normal safe STOP
        # transition, then RunController cancellation closes camera/serial.
        self.stop()

        self.status_var.set(
            "Stopping active workspace before mode change..."
        )

        def finish_mode_switch() -> None:
            controller_done = self.controller.join(
                0
            )

            analysis_done = (
                self._analysis_snapshot_jobs.unfinished_tasks
                == 0
            )

            if (
                controller_done
                and analysis_done
            ):
                self._reset_workspace_for_mode_selection()
                return

            self.after(
                50,
                finish_mode_switch,
            )

        finish_mode_switch()

    def _reset_workspace_for_mode_selection(
        self,
    ) -> None:
        """Discard in-memory workspace state and show a fresh mode selector."""

        self.withdraw()

        # Remove the active workspace/menu only after runtime resources are
        # confirmed closed. Previous session files on disk are preserved.
        self.configure(
            menu=""
        )

        for child in self.winfo_children():
            child.destroy()

        self.front_panel = None
        self.property_vars.clear()
        self.breakpoints.clear()
        self.probes.clear()
        self.current_diagram_id = None
        self.clipboard_node = None

        self.path = None
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()

        self.project = Project()
        self.current_vi_id = self.project.main_vi
        self.graph = self.project.main.graph

        # A new runtime/controller guarantees that no session state, camera,
        # serial handle, queued control, or telemetry from the previous mode
        # can leak into the next workspace.
        self.runtime = DataflowRuntime()
        self.controller = RunController(
            self.runtime
        )

        self.continuous = False
        self._latest_runtime_result = None
        self._last_runtime_ui_update = 0.0

        self._measurement_run_active = False
        self._measurement_exported = False
        self._last_motor_control = False
        self._measurement_run_counter = 0

        self._capture_reference_reset_pending = False
        self._global_stop_reset_pending = False
        self._global_stop_indicator_started_at = 0.0

        self._gradual_stop_in_progress = False

        self._pre_run_camera_ready = False
        self._pre_run_calibration_ready = False
        self._hardware_camera_connected = False
        self._hardware_arduino_connected = False

        self._stage_display_override_active = False

        self.session_root = None
        self.session_id = None
        self.session_started_at = None

        self.operating_mode = None

        self._startup_screen = StartupScreen(
            self,
            self._startup_logo_path(),
            self._complete_startup,
            show_splash=False,
        )

    # ============================================================
    # STARTUP WORKSPACE LAYOUT
    # ============================================================

    def _ask_collapse_workspace_panels(
        self,
    ) -> None:

        collapse = messagebox.askyesno(
            "Workspace Layout",
            (
                "Tutup semua panel samping dan bawah?\n\n"
                "Yes = tutup Node Library, Properties, dan "
                "Execution Log / Debugger Trace.\n"
                "No = tetap tampil seperti biasa."
            ),
            parent=self,
        )

        if collapse:
            self._collapse_workspace_panels()

    def _collapse_workspace_panels(
        self,
    ) -> None:

        work = getattr(
            self,
            "_work_panes",
            None,
        )

        vertical = getattr(
            self,
            "_vertical_panes",
            None,
        )

        if (
            work is None
            or vertical is None
        ):
            return

        # Make sure geometry is current before moving the sashes.
        self.update_idletasks()

        work_width = max(
            1,
            work.winfo_width(),
        )

        vertical_height = max(
            1,
            vertical.winfo_height(),
        )

        try:
            # Horizontal panes:
            # sash 0 -> left Node Library to the far left.
            # sash 1 -> right Properties to the far right.
            work.sashpos(
                0,
                0,
            )

            work.sashpos(
                1,
                work_width,
            )

            # Vertical pane:
            # sash 0 -> bottom console to the bottom edge.
            vertical.sashpos(
                0,
                vertical_height,
            )

        except tk.TclError:
            # Layout convenience must never prevent normal application use.
            return

        self.status_var.set(
            "Workspace side and bottom panels collapsed"
        )

    # ============================================================
    # STYLE
    # ============================================================

    def _build_style(self) -> None:

        style = ttk.Style(
            self
        )

        if "clam" in style.theme_names():
            style.theme_use(
                "clam"
            )

        style.configure(
            "Toolbar.TFrame",
            background="#273244",
        )

        style.configure(
            "Run.TButton",
            font=(
                "TkDefaultFont",
                10,
                "bold",
            ),
        )

    # ============================================================
    # MENU
    # ============================================================

    def _build_menu(self) -> None:

        menu = tk.Menu(
            self
        )

        # --------------------------------------------------------
        # FILE
        # --------------------------------------------------------

        file_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        file_menu.add_command(
            label="New",
            accelerator="Ctrl+N",
            command=self.new_project,
        )

        file_menu.add_command(
            label="Open...",
            accelerator="Ctrl+O",
            command=self.open_project,
        )

        file_menu.add_separator()

        file_menu.add_command(
            label="Save",
            accelerator="Ctrl+S",
            command=self.save_project,
        )

        file_menu.add_command(
            label="Save As...",
            accelerator="Ctrl+Shift+S",
            command=self.save_project_as,
        )

        file_menu.add_command(
            label="Export Verilog...",
            command=self.export_verilog,
        )

        file_menu.add_separator()

        file_menu.add_command(
            label="Exit",
            command=self.close_app,
        )

        menu.add_cascade(
            label="File",
            menu=file_menu,
        )

        # --------------------------------------------------------
        # EDIT
        # --------------------------------------------------------

        edit_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        edit_menu.add_command(
            label="Undo",
            accelerator="Ctrl+Z",
            command=self.undo,
        )

        edit_menu.add_command(
            label="Redo",
            accelerator="Ctrl+Y",
            command=self.redo,
        )

        edit_menu.add_separator()

        edit_menu.add_command(
            label="Copy Node",
            accelerator="Ctrl+C",
            command=self.copy_node,
        )

        edit_menu.add_command(
            label="Paste Node",
            accelerator="Ctrl+V",
            command=self.paste_node,
        )

        edit_menu.add_command(
            label="Delete",
            accelerator="Del",
            command=lambda: (
                self.canvas.delete_selection()
            ),
        )

        menu.add_cascade(
            label="Edit",
            menu=edit_menu,
        )

        # --------------------------------------------------------
        # RUN
        # --------------------------------------------------------

        run_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        run_menu.add_command(
            label="Run Continuously",
            accelerator="F6",
            command=self.toggle_continuous,
        )

        run_menu.add_command(
            label="Stop",
            accelerator="Shift+F6",
            command=self.stop,
        )

        run_menu.add_separator()

        run_menu.add_command(
            label="Pause",
            command=self.pause_run,
        )

        run_menu.add_command(
            label="Resume",
            command=self.resume_run,
        )

        run_menu.add_command(
            label="Single Step",
            command=self.step_run,
        )

        menu.add_cascade(
            label="Run",
            menu=run_menu,
        )

        # --------------------------------------------------------
        # VIEW
        # --------------------------------------------------------

        view_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        view_menu.add_command(
            label="Front Panel",
            accelerator="Ctrl+F",
            command=self.show_front_panel,
        )

        view_menu.add_command(
            label="Plugin Status",
            command=self.show_plugins,
        )

        view_menu.add_command(
            label="Hardware / Integration Diagnostics",
            command=self.show_diagnostics,
        )

        menu.add_cascade(
            label="View",
            menu=view_menu,
        )

        # --------------------------------------------------------
        # MODE
        # --------------------------------------------------------

        mode_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        mode_menu.add_command(
            label="Ganti Mode",
            command=self.change_mode,
        )

        menu.add_cascade(
            label="Mode",
            menu=mode_menu,
        )

        # --------------------------------------------------------
        # HELP
        # --------------------------------------------------------

        help_menu = tk.Menu(
            menu,
            tearoff=False,
        )

        help_menu.add_command(
            label="Quick Help",
            command=self.show_help,
        )

        help_menu.add_command(
            label="About",
            command=self.show_about,
        )

        menu.add_cascade(
            label="Help",
            menu=help_menu,
        )

        self.configure(
            menu=menu
        )

    # ============================================================
    # MAIN UI
    # ============================================================

    def _build_ui(self) -> None:

        self._build_toolbar()
        self._build_hardware_status_dashboard()

        work, console = (
            self._build_panes()
        )

        (
            library,
            center,
            inspector,
        ) = self._build_workspace_panes(
            work
        )

        self._build_library(
            library
        )

        self._build_workspace(
            center
        )

        self._build_inspector(
            inspector
        )

        self._build_console(
            console
        )

        self._build_status()

    # ============================================================
    # TOOLBAR
    # ============================================================

    def _build_toolbar(self) -> None:

        toolbar = ttk.Frame(
            self,
            style="Toolbar.TFrame",
            padding=6,
        )

        toolbar.pack(
            fill="x"
        )

        for text, command in (
            (
                "New",
                self.new_project,
            ),
            (
                "Open",
                self.open_project,
            ),
            (
                "Save",
                self.save_project,
            ),
        ):

            ttk.Button(
                toolbar,
                text=text,
                command=command,
            ).pack(
                side="left",
                padx=2,
            )

        ttk.Separator(
            toolbar,
            orient="vertical",
        ).pack(
            side="left",
            fill="y",
            padx=8,
        )

        self.run_button = ttk.Button(
            toolbar,
            text="Continuous",
            command=self.toggle_continuous,
        )

        self.run_button.pack(
            side="left",
            padx=2,
        )

        actions = (
            (
                "Stop",
                self.stop,
            ),
            (
                "Stop Bertahap",
                self.stop_gradually,
            ),
            (
                "Front Panel",
                self.show_front_panel,
            ),
            (
                "Validate",
                self.validate_current,
            ),
            (
                "Connector",
                self.configure_connector,
            ),
            (
                "Create SubVI",
                self.create_subvi,
            ),
            (
                "Breakpoint",
                self.toggle_breakpoint,
            ),
            (
                "Probe",
                self.toggle_probe,
            ),
            (
                "Open Structure",
                self.open_structure,
            ),
            (
                "Root Diagram",
                self.open_root_diagram,
            ),
        )

        for text, command in actions:

            ttk.Button(
                toolbar,
                text=text,
                command=command,
            ).pack(
                side="left",
                padx=(
                    10
                    if text
                    == "Front Panel"
                    else 2
                ),
            )

        self.zoom_label = ttk.Label(
            toolbar,
            text="Ctrl+wheel: zoom",
        )

        self.zoom_label.pack(
            side="right",
            padx=8,
        )

    # ============================================================
    # HARDWARE STATUS DASHBOARD
    # ============================================================

    def _build_hardware_status_dashboard(
        self,
    ) -> None:

        frame = ttk.Frame(
            self,
            padding=(
                8,
                4,
            ),
        )

        frame.pack(
            fill="x",
        )

        ttk.Label(
            frame,
            text="Hardware Status:",
            font=(
                "TkDefaultFont",
                9,
                "bold",
            ),
        ).pack(
            side="left",
        )

        self.hardware_camera_var = tk.StringVar(
            value="Camera: Disconnected"
        )

        self.hardware_arduino_var = tk.StringVar(
            value="Arduino: Disconnected"
        )

        self.hardware_com_var = tk.StringVar(
            value="COM: --"
        )

        self.hardware_camera_source_var = tk.StringVar(
            value="Camera Source: --"
        )

        for variable in (
            self.hardware_camera_var,
            self.hardware_arduino_var,
            self.hardware_com_var,
            self.hardware_camera_source_var,
        ):
            ttk.Label(
                frame,
                textvariable=variable,
            ).pack(
                side="left",
                padx=(
                    10,
                    0,
                ),
            )

        self._refresh_hardware_status_dashboard()

    def _refresh_hardware_status_dashboard(
        self,
    ) -> None:

        if not hasattr(
            self,
            "hardware_camera_var",
        ):
            return

        controls = (
            self.front_panel.control_values()
            if self.front_panel
            else {}
        )

        com_port = str(
            controls.get(
                "com",
                "",
            )
        ).strip()

        camera_mode = str(
            controls.get(
                "oil_mode",
                "",
            )
        ).strip().lower()

        if camera_mode == "network":
            camera_source = str(
                controls.get(
                    "wifi",
                    "",
                )
            ).strip()

        elif camera_mode:
            camera_source = (
                "USB device "
                + str(
                    controls.get(
                        "oil_source",
                        "--",
                    )
                )
            )

        else:
            camera_source = "--"

        camera_text = (
            "Camera: "
            + (
                "Connected"
                if self._hardware_camera_connected
                else "Disconnected"
            )
        )

        arduino_text = (
            "Arduino: "
            + (
                "Connected"
                if self._hardware_arduino_connected
                else "Disconnected"
            )
        )

        com_text = (
            "COM: "
            + (
                com_port
                if com_port
                else "--"
            )
        )

        camera_source_text = (
            "Camera Source: "
            + (
                camera_source
                if camera_source
                else "--"
            )
        )

        if self.hardware_camera_var.get() != camera_text:
            self.hardware_camera_var.set(
                camera_text
            )

        if self.hardware_arduino_var.get() != arduino_text:
            self.hardware_arduino_var.set(
                arduino_text
            )

        if self.hardware_com_var.get() != com_text:
            self.hardware_com_var.set(
                com_text
            )

        if (
            self.hardware_camera_source_var.get()
            != camera_source_text
        ):
            self.hardware_camera_source_var.set(
                camera_source_text
            )

    # ============================================================
    # PANES
    # ============================================================

    def _build_panes(self):

        vertical = ttk.Panedwindow(
            self,
            orient="vertical",
        )

        self._vertical_panes = vertical

        vertical.pack(
            fill="both",
            expand=True,
        )

        work = ttk.Panedwindow(
            vertical,
            orient="horizontal",
        )

        self._work_panes = work

        vertical.add(
            work,
            weight=5,
        )

        console = ttk.Frame(
            vertical,
            padding=4,
        )

        vertical.add(
            console,
            weight=1,
        )

        return (
            work,
            console,
        )

    def _build_workspace_panes(
        self,
        work,
    ):

        panes = (
            ttk.LabelFrame(
                work,
                text="Node Library",
                padding=6,
            ),
            ttk.Frame(
                work
            ),
            ttk.LabelFrame(
                work,
                text="Properties",
                padding=8,
            ),
        )

        for pane, weight in zip(
            panes,
            (
                1,
                5,
                1,
            ),
        ):

            work.add(
                pane,
                weight=weight,
            )

        return panes

    # ============================================================
    # LIBRARY
    # ============================================================

    def _build_library(
        self,
        library,
    ) -> None:

        ttk.Label(
            library,
            text="VI Explorer",
            font=(
                "TkDefaultFont",
                10,
                "bold",
            ),
        ).pack(
            anchor="w"
        )

        self.vi_list = tk.Listbox(
            library,
            height=5,
            exportselection=False,
        )

        self.vi_list.pack(
            fill="x",
            pady=(
                3,
                2,
            ),
        )

        self.vi_list.bind(
            "<<ListboxSelect>>",
            self._switch_vi_event,
        )

        buttons = ttk.Frame(
            library
        )

        buttons.pack(
            fill="x",
            pady=(
                0,
                8,
            ),
        )

        for (
            text,
            width,
            command,
        ) in (
            (
                "+",
                3,
                self.add_vi,
            ),
            (
                "Rename",
                None,
                self.rename_vi,
            ),
            (
                "Delete",
                None,
                self.delete_vi,
            ),
            (
                "Main",
                None,
                self.set_main_vi,
            ),
        ):

            options = (
                {
                    "width": width
                }
                if width
                else {}
            )

            ttk.Button(
                buttons,
                text=text,
                command=command,
                **options,
            ).pack(
                side="left",
                padx=(
                    2
                    if text
                    in (
                        "Rename",
                        "Main",
                    )
                    else 0
                ),
            )

        ttk.Label(
            library,
            text="Node Search",
            font=(
                "TkDefaultFont",
                10,
                "bold",
            ),
        ).pack(
            anchor="w"
        )

        self.search_var = (
            tk.StringVar()
        )

        ttk.Entry(
            library,
            textvariable=self.search_var,
        ).pack(
            fill="x",
            pady=(
                3,
                4,
            ),
        )

        self.search_var.trace_add(
            "write",
            lambda *_args: (
                self._populate_library()
            ),
        )

        self.library_tree = (
            ttk.Treeview(
                library,
                show="tree",
                selectmode="browse",
            )
        )

        self.library_tree.pack(
            fill="both",
            expand=True,
        )

        self.library_tree.bind(
            "<Double-1>",
            self._library_add,
        )

        self._populate_library()
        self._refresh_vi_list()

        ttk.Label(
            library,
            text="Double-click to add",
            foreground="#58677a",
        ).pack(
            pady=(
                5,
                0,
            )
        )

    # ============================================================
    # WORKSPACE
    # ============================================================

    def _build_workspace(
        self,
        center,
    ) -> None:

        self.workspace = (
            ttk.Notebook(
                center
            )
        )

        self.workspace.pack(
            fill="both",
            expand=True,
        )

        panel_tab = ttk.Frame(
            self.workspace
        )

        diagram_tab = ttk.Frame(
            self.workspace
        )

        self.workspace.add(
            panel_tab,
            text="Front Panel",
        )

        self.workspace.add(
            diagram_tab,
            text="Block Diagram",
        )

        tools = ttk.Frame(
            panel_tab,
            padding=4,
        )

        tools.pack(
            fill="x"
        )

        ttk.Button(
            tools,
            text="Edit",
            command=lambda: (
                self.front_panel.set_mode(
                    "edit"
                )
            ),
        ).pack(
            side="left"
        )

        ttk.Button(
            tools,
            text="Operate",
            command=lambda: (
                self.front_panel.set_mode(
                    "operate"
                )
            ),
        ).pack(
            side="left",
            padx=4,
        )

        panel = (
            self.project.main.front_panel
        )

        self.project.main.front_panel = (
            panel
            if "items" in panel
            else self.project.to_dict()[
                "vis"
            ][0]["front_panel"]
        )

        # ============================================================
        # FRONT PANEL CANVAS + VERTICAL SCROLLBAR
        #
        # Patch:
        # Menambahkan scrollbar vertikal visual di sisi kanan
        # Front Panel.
        #
        # Mouse wheel / zoom / behavior PanelDesigner tetap
        # menggunakan implementasi yang sudah ada.
        # ============================================================

        front_panel_canvas_frame = (
            ttk.Frame(
                panel_tab
            )
        )

        front_panel_canvas_frame.pack(
            fill="both",
            expand=True,
        )


        self.front_panel = (
            PanelDesigner(
                front_panel_canvas_frame,
                self.graph,
                self.project.main.front_panel,
                self._panel_changed,
                self._panel_values_changed,
            )
        )


        front_panel_scrollbar = (
            ttk.Scrollbar(
                front_panel_canvas_frame,
                orient="vertical",
                command=self.front_panel.yview,
            )
        )


        self.front_panel.configure(
            yscrollcommand=front_panel_scrollbar.set
        )


        self.project.main.front_panel = (
            self.front_panel.panel
        )


        self.front_panel.pack(
            side="left",
            fill="both",
            expand=True,
        )


        front_panel_scrollbar.pack(
            side="right",
            fill="y",
        )


        # ============================================================
        # BLOCK DIAGRAM CANVAS + VERTICAL SCROLLBAR
        #
        # Patch:
        # Menambahkan scrollbar vertikal visual di sisi kanan
        # Block Diagram.
        #
        # Mouse wheel / zoom / edit behavior DiagramCanvas tetap
        # menggunakan implementasi yang sudah ada.
        # ============================================================

        diagram_canvas_frame = (
            ttk.Frame(
                diagram_tab
            )
        )

        diagram_canvas_frame.pack(
            fill="both",
            expand=True,
        )


        self.canvas = (
            DiagramCanvas(
                diagram_canvas_frame,
                self.graph,
                self.select_node,
                self.checkpoint,
                self.changed,
                self._connection_error,
                self._delete_node_resources,
            )
        )


        diagram_scrollbar = (
            ttk.Scrollbar(
                diagram_canvas_frame,
                orient="vertical",
                command=self.canvas.yview,
            )
        )


        self.canvas.configure(
            yscrollcommand=diagram_scrollbar.set
        )


        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )


        diagram_scrollbar.pack(
            side="right",
            fill="y",
        )

    # ============================================================
    # INSPECTOR
    # ============================================================

    def _build_inspector(
        self,
        inspector,
    ) -> None:

        self.inspector_body = (
            ttk.Frame(
                inspector
            )
        )

        self.inspector_body.pack(
            fill="both",
            expand=True,
        )

        self.select_node(
            None
        )

    # ============================================================
    # CONSOLE
    # ============================================================

    def _build_console(
        self,
        frame,
    ) -> None:

        tabs = ttk.Notebook(
            frame
        )

        tabs.pack(
            fill="both",
            expand=True,
        )

        log_tab = ttk.Frame(
            tabs
        )

        debug_tab = ttk.Frame(
            tabs
        )

        tabs.add(
            log_tab,
            text="Execution Log",
        )

        tabs.add(
            debug_tab,
            text="Debugger Trace",
        )

        self.console = tk.Text(
            log_tab,
            height=7,
            background="#10151d",
            foreground="#d7e1ef",
            insertbackground="white",
            font=(
                "TkFixedFont",
                9,
            ),
            state="disabled",
        )

        scroll = ttk.Scrollbar(
            log_tab,
            command=self.console.yview,
        )

        self.console.configure(
            yscrollcommand=scroll.set
        )

        self.console.pack(
            side="left",
            fill="both",
            expand=True,
        )

        scroll.pack(
            side="right",
            fill="y",
        )

        buttons = ttk.Frame(
            debug_tab
        )

        buttons.pack(
            fill="x"
        )

        for text, command in (
            (
                "Pause",
                self.pause_run,
            ),
            (
                "Resume",
                self.resume_run,
            ),
            (
                "Step",
                self.step_run,
            ),
        ):

            ttk.Button(
                buttons,
                text=text,
                command=command,
            ).pack(
                side="left",
                padx=(
                    3
                    if text
                    == "Resume"
                    else 0
                ),
            )

        self.trace_tree = (
            ttk.Treeview(
                debug_tab,
                columns=(
                    "seq",
                    "event",
                    "node",
                    "value",
                ),
                show="headings",
                height=6,
            )
        )

        for column, width in (
            (
                "seq",
                55,
            ),
            (
                "event",
                120,
            ),
            (
                "node",
                130,
            ),
            (
                "value",
                500,
            ),
        ):

            self.trace_tree.heading(
                column,
                text=column.title(),
            )

            self.trace_tree.column(
                column,
                width=width,
            )

        self.trace_tree.pack(
            fill="both",
            expand=True,
        )

    # ============================================================
    # STATUS
    # ============================================================

    def _build_status(self) -> None:

        self.status_var = (
            tk.StringVar(
                value="Ready"
            )
        )

        ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            padding=(
                7,
                3,
            ),
        ).pack(
            fill="x"
        )

    # ============================================================
    # LIBRARY POPULATION
    # ============================================================

    def _populate_library(
        self,
    ) -> None:

        if not hasattr(
            self,
            "library_tree",
        ):
            return

        self.library_tree.delete(
            *self.library_tree.get_children()
        )

        query = (
            self.search_var.get().strip().lower()
            if hasattr(
                self,
                "search_var",
            )
            else ""
        )

        categories: dict[
            str,
            str,
        ] = {}

        for (
            node_type,
            definition,
        ) in NODE_DEFINITIONS.items():

            if (
                node_type == "subvi"
                or (
                    query
                    and query
                    not in (
                        f"{definition.title} "
                        f"{definition.category} "
                        f"{node_type}"
                    ).lower()
                )
            ):
                continue

            parent = categories.setdefault(
                definition.category,
                self.library_tree.insert(
                    "",
                    "end",
                    text=definition.category,
                    open=True,
                ),
            )

            self.library_tree.insert(
                parent,
                "end",
                iid=f"type:{node_type}",
                text=definition.title,
            )

    # ============================================================
    # CONNECTION ERROR
    # ============================================================

    def _connection_error(
        self,
        message: str,
    ) -> None:

        self.status_var.set(
            message
        )

        self.log(
            "WIRE ERROR "
            + message
        )

    # ============================================================
    # SHORTCUTS
    # ============================================================

    def _bind_shortcuts(
        self,
    ) -> None:

        self.bind_all(
            "<Control-n>",
            lambda _e: (
                self.new_project()
            ),
        )

        self.bind_all(
            "<Control-o>",
            lambda _e: (
                self.open_project()
            ),
        )

        self.bind_all(
            "<Control-s>",
            lambda _e: (
                self.save_project()
            ),
        )

        self.bind_all(
            "<Control-Shift-S>",
            lambda _e: (
                self.save_project_as()
            ),
        )

        self.bind_all(
            "<Control-z>",
            lambda _e: (
                self.undo()
            ),
        )

        self.bind_all(
            "<Control-y>",
            lambda _e: (
                self.redo()
            ),
        )

        self.bind_all(
            "<Control-c>",
            lambda _e: (
                self.copy_node()
            ),
        )

        self.bind_all(
            "<Control-v>",
            lambda _e: (
                self.paste_node()
            ),
        )

        self.bind_all(
            "<Control-f>",
            lambda _e: (
                self.show_front_panel()
            ),
        )

        self.bind_all(
            "<F6>",
            lambda _e: (
                self.toggle_continuous()
            ),
        )

        self.bind_all(
            "<Shift-F6>",
            lambda _e: (
                self.stop()
            ),
        )

    # ============================================================
    # ADD LIBRARY NODE
    # ============================================================

    def _library_add(
        self,
        _event: tk.Event,
    ) -> None:

        item = (
            self.library_tree.focus()
        )

        if not item.startswith(
            "type:"
        ):
            return

        node_type = (
            item.split(
                ":",
                1,
            )[1]
        )

        self.checkpoint()

        offset = (
            len(
                self.graph.nodes
            )
            % 8
        )

        node = (
            self.graph.add_node(
                node_type,
                80
                + offset
                * 22,
                70
                + offset
                * 22,
            )
        )

        if node_type in (
            "visual_case",
            "visual_for",
        ):
            self._initialize_structure(
                node
            )

        self.canvas.selected_node = (
            node.id
        )

        self.changed()

        self.select_node(
            node.id
        )

        self.canvas.redraw()

    # ============================================================
    # UNDO / REDO
    # ============================================================

    def checkpoint(self) -> None:

        self.undo_stack.append(
            project_snapshot(
                self.project,
                self.current_vi_id,
            )
        )

        del self.undo_stack[:-100]

        self.redo_stack.clear()

    def changed(self) -> None:

        self.dirty = True
        self.canvas.statuses = {}

        self._update_title()

        if (
            self.front_panel
            and self.current_diagram_id
            is None
        ):

            vi = (
                self.project.vis[
                    self.current_vi_id
                ]
            )

            self.front_panel.set_document(
                vi.graph,
                vi.front_panel,
            )

            vi.front_panel = (
                self.front_panel.panel
            )

    def _panel_changed(
        self,
    ) -> None:

        self.project.vis[
            self.current_vi_id
        ].front_panel = (
            self.front_panel.panel
        )

        self.dirty = True

        self._update_title()

    # ============================================================
    # SPINNING-DROP PRE-RUN CHECKLIST
    # ============================================================

    @staticmethod
    def _pre_run_positive_number(
        value: Any,
    ) -> bool:

        try:
            number = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return False

        return (
            math.isfinite(
                number
            )
            and number > 0.0
        )

    def _spinning_drop_pre_run_check(
        self,
        values: dict[
            str,
            Any,
        ],
    ) -> bool:

        if self.operating_mode not in (
            "standard",
            "manual",
        ):
            return True

        checks: list[
            tuple[
                bool,
                str,
            ]
        ] = []

        run_graph = (
            self.project.vis[
                self.current_vi_id
            ].graph
        )

        validation_errors = (
            self.runtime.validate(
                run_graph,
                self.project,
                self.current_vi_id,
            )
        )

        checks.append(
            (
                not validation_errors,
                "Project validation",
            )
        )

        checks.append(
            (
                (
                    self.controller.running
                    and self.continuous
                ),
                "Continuous mode active",
            )
        )

        com_port = str(
            values.get(
                "com",
                "",
            )
        ).strip()

        checks.append(
            (
                bool(
                    com_port
                ),
                (
                    (
                        f"COM Arduino: {com_port} "
                        "(recheck port in Windows Device Manager)"
                    )
                    if com_port
                    else (
                        "COM Arduino configured "
                        "(recheck port in Windows Device Manager)"
                    )
                ),
            )
        )

        camera_mode = str(
            values.get(
                "oil_mode",
                "",
            )
        ).strip().lower()

        camera_configured = bool(
            camera_mode
        )

        if camera_mode == "network":
            camera_configured = bool(
                str(
                    values.get(
                        "wifi",
                        "",
                    )
                ).strip()
            )

        elif camera_mode:
            try:
                camera_configured = (
                    float(
                        values.get(
                            "oil_source",
                            -1,
                        )
                    )
                    >= 0.0
                )
            except (
                TypeError,
                ValueError,
            ):
                camera_configured = False

        checks.append(
            (
                camera_configured,
                "Camera configuration valid",
            )
        )

        checks.append(
            (
                self._pre_run_camera_ready,
                "Camera live frame available",
            )
        )

        checks.append(
            (
                self._pre_run_positive_number(
                    values.get(
                        "wire_known"
                    )
                ),
                "Known wire diameter valid",
            )
        )

        checks.append(
            (
                self._pre_run_calibration_ready,
                "Wire calibration / scale factor available",
            )
        )

        density_mode = str(
            values.get(
                "density_mode",
                "",
            )
        ).strip()

        density_valid = False

        if density_mode == "Manual Δρ":
            density_valid = (
                self._pre_run_positive_number(
                    values.get(
                        "density_input"
                    )
                )
            )

        elif density_mode == "Template":

            templates = {
                "Water": 1000.0,
                "Oil": 850.0,
            }

            def resolved_density(
                fluid_key: str,
                value_key: str,
            ) -> float | None:

                fluid = str(
                    values.get(
                        fluid_key,
                        "",
                    )
                ).strip()

                if fluid in templates:
                    return templates[
                        fluid
                    ]

                if fluid != "Custom":
                    return None

                raw = values.get(
                    value_key
                )

                if not self._pre_run_positive_number(
                    raw
                ):
                    return None

                return float(
                    raw
                )

            density_1 = resolved_density(
                "fluid_1",
                "density_1",
            )

            density_2 = resolved_density(
                "fluid_2",
                "density_2",
            )

            density_valid = (
                density_1 is not None
                and density_2 is not None
                and abs(
                    density_1
                    - density_2
                ) > 0.0
            )

        checks.append(
            (
                density_valid,
                "Density input valid",
            )
        )

        if self.operating_mode == "manual":

            try:
                target_rpm = float(
                    values.get(
                        "manual_target_rpm",
                        0.0,
                    )
                )

                target_valid = (
                    math.isfinite(
                        target_rpm
                    )
                    and 0.0
                    < target_rpm
                    <= 6000.0
                )

            except (
                TypeError,
                ValueError,
            ):
                target_valid = False

            checks.append(
                (
                    target_valid,
                    "Manual Target RPM valid (1-6000)",
                )
            )

        failed = [
            label
            for ok, label
            in checks
            if not ok
        ]

        if not failed:
            self.status_var.set(
                "Pre-run checklist passed"
            )
            return True

        if self.front_panel:
            self.front_panel.sync_control_value_from_model(
                "motor",
                False,
            )

            self._last_motor_control = False

            if self.controller.running:
                safe_values = dict(
                    values
                )

                safe_values[
                    "motor"
                ] = False

                self.controller.update_controls(
                    safe_values
                )

            self.front_panel.redraw()

        checklist_text = "\n".join(
            (
                "✓ "
                if ok
                else "✗ "
            )
            + label
            for ok, label
            in checks
        )

        self.status_var.set(
            "Pre-run checklist failed"
        )

        messagebox.showwarning(
            "Pre-Run Checklist",
            (
                checklist_text
                + "\n\nMeasurement cannot start. "
                "Correct the failed item(s) and try again."
            ),
            parent=self,
        )

        return False

    def _panel_values_changed(
        self,
        values: dict[
            str,
            Any,
        ],
    ) -> None:

        self._refresh_hardware_status_dashboard()

        # Front Panel Global STOP is momentary.
        #
        # The actual stop request is issued immediately. After that request
        # has been sent, flush pending Tk drawing work so the already-redrawn
        # Global STOP control becomes visible even when shutdown is extremely
        # fast. The small minimum-visible interval is UI-only and never delays
        # motor/runtime shutdown.
        if bool(
            values.get(
                "global_stop",
                False,
            )
        ):
            self._global_stop_reset_pending = True
            self._global_stop_indicator_started_at = time.monotonic()

            # Keep the existing global-stop path exactly as-is.
            self.stop()

            # _press() and _set_motor_stopped() have already redrawn the
            # Front Panel with global_stop=True. Force Tk to paint that state
            # now instead of waiting for the event handler to return.
            if self.front_panel:
                self.front_panel.update_idletasks()

            return

        # Capture Reference is momentary in both Standard and Manual
        # modes. Keep True until the runtime has actually completed
        # one graph result with capture_wire=True; _apply_result()
        # then returns the control to False automatically.
        if bool(
            values.get(
                "capture_wire",
                False,
            )
        ):

            # A new operator reference becomes visible again until the next
            # automatic stage-sample burst starts.
            self._stage_display_override_active = False

            self._capture_reference_reset_pending = True

            if self.controller.running:
                self.controller.update_controls(
                    values
                )

            return

        previous_motor = self._last_motor_control

        current_motor = bool(
            values.get(
                "motor",
                previous_motor,
            )
        )

        if (
            current_motor
            and not previous_motor
        ):
            if not self._spinning_drop_pre_run_check(
                values
            ):
                return

            self._stage_display_override_active = False

            self._measurement_run_active = True
            self._measurement_exported = False

        if (
            previous_motor
            and not current_motor
        ):
            self._export_measurement_table()

        self._last_motor_control = current_motor

        if self.controller.running:

            self.controller.update_controls(
                values
            )

    def undo(self) -> None:

        if not self.undo_stack:
            return

        self.redo_stack.append(
            project_snapshot(
                self.project,
                self.current_vi_id,
            )
        )

        self._restore_snapshot(
            self.undo_stack.pop()
        )

        self.dirty = True

        self._update_title()

    def redo(self) -> None:

        if not self.redo_stack:
            return

        self.undo_stack.append(
            project_snapshot(
                self.project,
                self.current_vi_id,
            )
        )

        self._restore_snapshot(
            self.redo_stack.pop()
        )

        self.dirty = True

        self._update_title()

    def _restore_snapshot(
        self,
        snapshot: dict[
            str,
            Any,
        ],
    ) -> None:

        (
            self.project,
            self.current_vi_id,
        ) = restore_project_snapshot(
            snapshot
        )

        self._replace_graph(
            self.project.vis[
                self.current_vi_id
            ].graph
        )

        self._refresh_vi_list()

    # ============================================================
    # COPY / PASTE
    # ============================================================

    def copy_node(self) -> None:

        node_id = (
            self.canvas.selected_node
        )

        if not node_id:
            return

        node = (
            self.graph.nodes[
                node_id
            ]
        )

        self.clipboard_node = {
            "type": node.type,
            "label": node.label,
            "properties": copy.deepcopy(
                node.properties
            ),
            "x": node.x,
            "y": node.y,
        }

        self.status_var.set(
            f"Copied node: {node.label}"
        )

    def paste_node(self) -> None:

        if not self.clipboard_node:
            return

        self.checkpoint()

        data = (
            self.clipboard_node
        )

        node = (
            self.graph.add_node(
                data["type"],
                data["x"] + 30,
                data["y"] + 30,
            )
        )

        node.label = (
            data["label"]
            + " Copy"
        )

        node.properties = (
            copy.deepcopy(
                data["properties"]
            )
        )

        if node.type in (
            "visual_case",
            "visual_for",
        ):

            node.properties = (
                self._clone_structure_properties(
                    node.type,
                    node.properties,
                )
            )

        self.clipboard_node[
            "x"
        ] = node.x

        self.clipboard_node[
            "y"
        ] = node.y

        self.canvas.selected_node = (
            node.id
        )

        self.changed()

        self.select_node(
            node.id
        )

        self.canvas.redraw()

    # ============================================================
    # INSPECTOR
    # ============================================================

    def select_node(
        self,
        node_id: str | None,
    ) -> None:

        for child in (
            self.inspector_body.winfo_children()
        ):
            child.destroy()

        self.property_vars.clear()

        if (
            not node_id
            or node_id
            not in self.graph.nodes
        ):

            ttk.Label(
                self.inspector_body,
                text=(
                    "Select a node to edit "
                    "its label and configuration."
                ),
                wraplength=180,
            ).pack(
                anchor="w"
            )

            return

        node = (
            self.graph.nodes[
                node_id
            ]
        )

        ttk.Label(
            self.inspector_body,
            text=(
                NODE_DEFINITIONS[
                    node.type
                ].title
            ),
            font=(
                "TkDefaultFont",
                11,
                "bold",
            ),
        ).pack(
            anchor="w",
            pady=(
                0,
                8,
            ),
        )

        fields = {
            "label": node.label,
            **node.properties,
        }

        for (
            key,
            value,
        ) in fields.items():

            ttk.Label(
                self.inspector_body,
                text=(
                    key.replace(
                        "_",
                        " ",
                    ).title()
                ),
            ).pack(
                anchor="w",
                pady=(
                    5,
                    1,
                ),
            )

            var = tk.StringVar(
                value=editor_value_text(
                    value
                )
            )

            if key == "display_type":

                entry = ttk.Combobox(
                    self.inspector_body,
                    textvariable=var,
                    state="readonly",
                    values=(
                        "auto",
                        "numeric",
                        "string",
                        "boolean",
                        "array",
                        "led",
                        "gauge",
                        "progress",
                        "thermometer",
                        "waveform_chart",
                    ),
                )

            else:

                entry = ttk.Entry(
                    self.inspector_body,
                    textvariable=var,
                )

            entry.pack(
                fill="x"
            )

            entry.bind(
                "<Return>",
                lambda _e, nid=node_id: (
                    self.apply_properties(
                        nid
                    )
                ),
            )

            self.property_vars[
                key
            ] = var

        ttk.Button(
            self.inspector_body,
            text="Apply",
            command=lambda: (
                self.apply_properties(
                    node_id
                )
            ),
        ).pack(
            fill="x",
            pady=12,
        )

    def apply_properties(
        self,
        node_id: str,
    ) -> None:

        if node_id not in self.graph.nodes:
            return

        node = (
            self.graph.nodes[
                node_id
            ]
        )

        new_label = (
            self.property_vars[
                "label"
            ].get().strip()
        )

        if not new_label:

            messagebox.showerror(
                "Invalid property",
                "Label cannot be empty.",
                parent=self,
            )

            return

        parsed: dict[
            str,
            Any,
        ] = {}

        try:

            for (
                key,
                variable,
            ) in self.property_vars.items():

                if key == "label":
                    continue

                old = (
                    node.properties.get(
                        key
                    )
                )

                raw = (
                    variable.get()
                )

                if isinstance(
                    old,
                    bool,
                ):

                    if (
                        raw.lower()
                        not in (
                            "true",
                            "false",
                        )
                    ):

                        raise ValueError(
                            f"{key} must be "
                            "true or false"
                        )

                    parsed[
                        key
                    ] = (
                        raw.lower()
                        == "true"
                    )

                elif isinstance(
                    old,
                    int,
                ):

                    parsed[
                        key
                    ] = int(
                        raw
                    )

                elif isinstance(
                    old,
                    float,
                ):

                    parsed[
                        key
                    ] = float(
                        raw
                    )

                elif isinstance(
                    old,
                    (
                        list,
                        dict,
                    ),
                ):

                    value = json.loads(
                        raw
                    )

                    if not isinstance(
                        value,
                        type(old),
                    ):

                        raise ValueError(
                            f"{key} must be a JSON "
                            f"{type(old).__name__}"
                        )

                    parsed[
                        key
                    ] = value

                else:

                    parsed[
                        key
                    ] = raw

        except ValueError as exc:

            messagebox.showerror(
                "Invalid property",
                str(exc),
                parent=self,
            )

            return

        self.checkpoint()

        node.label = new_label

        node.properties.update(
            parsed
        )

        if (
            self.front_panel
            and "value"
            in parsed
        ):

            self.front_panel.sync_control_value_from_model(
                node_id,
                node.properties[
                    "value"
                ],
            )

        self.changed()

        self.canvas.redraw()

        self.status_var.set(
            f"Updated {node.label}"
        )

    # ============================================================
    # SPINNING-DROP MEASUREMENT EXPORT
    # ============================================================

    @staticmethod
    def _xlsx_column_name(
        index: int,
    ) -> str:

        name = ""

        while index > 0:

            index, remainder = divmod(
                index - 1,
                26,
            )

            name = (
                chr(
                    65 + remainder
                )
                + name
            )

        return name

    @classmethod
    def _write_measurement_xlsx(
        cls,
        summary_rows: list[list[Any]],
        sample_rows: list[list[Any]],
        statistics_rows: list[list[Any]],
        destination: Path,
        *,
        session_id: str | None,
        mode_label: str,
    ) -> None:
        """
        Write one polished three-sheet spinning-drop workbook.

        Styling is intentionally restrained:
        - one dark title band
        - one soft metadata row
        - clear blue table headers
        - light alternating data rows
        - thin borders and practical column widths
        """

        exported_at = (
            datetime.now()
            .strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        session_text = (
            session_id
            if session_id
            else "Legacy / no active session"
        )

        metadata_text = (
            f"Session: {session_text}    |    "
            f"Mode: {mode_label}    |    "
            f"Exported: {exported_at}"
        )

        def number_format_id(
            sheet_name: str,
            column_index: int,
        ) -> int:

            if sheet_name == "Measurement Summary":
                if column_index in (2,):
                    return 4   # 0.000
                if column_index in (3, 4):
                    return 5   # 0.000000
                if column_index in (5, 6, 7):
                    return 6   # 0.000000E+00
                if column_index in (8, 9):
                    return 5   # 0.000000
                if column_index == 10:
                    return 7   # 0.00

            elif sheet_name == "Stage Samples":
                if column_index == 3:
                    return 4
                if column_index in (4, 5):
                    return 5

            elif sheet_name == "Statistics":
                if column_index in (3, 4, 5, 6):
                    return 4
                if column_index == 7:
                    return 7

            return 0

        def style_id(
            sheet_name: str,
            row_index: int,
            column_index: int,
            data_row_number: int | None,
        ) -> int:

            if row_index == 1:
                return 1

            if row_index == 2:
                return 2

            if row_index == 4:
                return 3

            base = (
                9
                if (
                    data_row_number is not None
                    and data_row_number % 2 == 0
                )
                else 8
            )

            fmt = number_format_id(
                sheet_name,
                column_index,
            )

            if fmt == 4:
                return base + 2
            if fmt == 5:
                return base + 4
            if fmt == 6:
                return base + 6
            if fmt == 7:
                return base + 8

            return base

        def cell_xml(
            sheet_name: str,
            row_index: int,
            column_index: int,
            value: Any,
            data_row_number: int | None = None,
        ) -> str:

            reference = (
                f"{cls._xlsx_column_name(column_index)}"
                f"{row_index}"
            )

            style = style_id(
                sheet_name,
                row_index,
                column_index,
                data_row_number,
            )

            if value is None:
                return (
                    f'<c r="{reference}" s="{style}"/>'
                )

            if isinstance(
                value,
                bool,
            ):
                return (
                    f'<c r="{reference}" s="{style}" t="b">'
                    f"<v>{1 if value else 0}</v>"
                    "</c>"
                )

            if isinstance(
                value,
                (int, float),
            ) and not isinstance(
                value,
                bool,
            ):
                number = float(
                    value
                )

                if not math.isfinite(
                    number
                ):
                    value = ""

                else:
                    return (
                        f'<c r="{reference}" s="{style}">'
                        f"<v>{value}</v>"
                        "</c>"
                    )

            text_value = escape(
                str(value)
            )

            preserve_space = (
                ' xml:space="preserve"'
                if (
                    str(value).startswith(" ")
                    or str(value).endswith(" ")
                )
                else ""
            )

            return (
                f'<c r="{reference}" s="{style}" t="inlineStr">'
                f"<is><t{preserve_space}>"
                f"{text_value}"
                "</t></is>"
                "</c>"
            )

        def worksheet_xml(
            sheet_name: str,
            title: str,
            rows: list[list[Any]],
            widths: list[float],
        ) -> str:

            max_columns = max(
                1,
                len(
                    rows[0]
                )
                if rows
                else len(
                    widths
                )
            )

            title_cells = [
                cell_xml(
                    sheet_name,
                    1,
                    1,
                    title,
                )
            ]

            title_cells.extend(
                cell_xml(
                    sheet_name,
                    1,
                    column,
                    None,
                )
                for column in range(
                    2,
                    max_columns + 1,
                )
            )

            metadata_cells = [
                cell_xml(
                    sheet_name,
                    2,
                    1,
                    metadata_text,
                )
            ]

            metadata_cells.extend(
                cell_xml(
                    sheet_name,
                    2,
                    column,
                    None,
                )
                for column in range(
                    2,
                    max_columns + 1,
                )
            )

            sheet_rows = [
                (
                    '<row r="1" ht="26" customHeight="1">'
                    + "".join(
                        title_cells
                    )
                    + "</row>"
                ),
                (
                    '<row r="2" ht="20" customHeight="1">'
                    + "".join(
                        metadata_cells
                    )
                    + "</row>"
                ),
                '<row r="3" ht="8" customHeight="1"/>',
            ]

            for data_index, row in enumerate(
                rows,
                start=0,
            ):

                excel_row = (
                    4
                    + data_index
                )

                row_cells = "".join(
                    cell_xml(
                        sheet_name,
                        excel_row,
                        column_index,
                        value,
                        (
                            None
                            if data_index == 0
                            else data_index
                        ),
                    )
                    for column_index, value
                    in enumerate(
                        row,
                        start=1,
                    )
                )

                row_height = (
                    22
                    if data_index == 0
                    else 19
                )

                sheet_rows.append(
                    f'<row r="{excel_row}" ht="{row_height}" '
                    'customHeight="1">'
                    + row_cells
                    + "</row>"
                )

            column_xml = "".join(
                (
                    f'<col min="{index}" max="{index}" '
                    f'width="{width}" customWidth="1"/>'
                )
                for index, width
                in enumerate(
                    widths,
                    start=1,
                )
            )

            last_row = max(
                4,
                3
                + len(
                    rows
                ),
            )

            last_column = cls._xlsx_column_name(
                max_columns
            )

            auto_filter = (
                f'<autoFilter ref="A4:{last_column}{last_row}"/>'
                if rows
                else ""
            )

            merged_cells = (
                '<mergeCells count="2">'
                f'<mergeCell ref="A1:{last_column}1"/>'
                f'<mergeCell ref="A2:{last_column}2"/>'
                "</mergeCells>"
            )

            return (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main">'
                '<sheetViews>'
                '<sheetView workbookViewId="0" showGridLines="0">'
                '<pane ySplit="4" topLeftCell="A5" '
                'activePane="bottomLeft" state="frozen"/>'
                '<selection pane="bottomLeft" activeCell="A5" sqref="A5"/>'
                '</sheetView>'
                '</sheetViews>'
                '<sheetFormatPr defaultRowHeight="18"/>'
                '<cols>'
                + column_xml
                + '</cols>'
                '<sheetData>'
                + "".join(
                    sheet_rows
                )
                + '</sheetData>'
                + auto_filter
                + merged_cells
                + '<pageMargins left="0.35" right="0.35" '
                'top="0.55" bottom="0.55" header="0.2" footer="0.2"/>'
                '<pageSetup orientation="landscape" fitToWidth="1" '
                'fitToHeight="0"/>'
                '</worksheet>'
            )

        summary_xml = worksheet_xml(
            "Measurement Summary",
            "GMJ Spinning Drop IFT — Measurement Summary",
            summary_rows,
            [
                12,
                16,
                17,
                17,
                16,
                17,
                17,
                18,
                17,
                13,
            ],
        )

        samples_xml = worksheet_xml(
            "Stage Samples",
            "GMJ Spinning Drop IFT — Stage Samples",
            sample_rows,
            [
                12,
                11,
                16,
                17,
                26,
                64,
            ],
        )

        statistics_xml = worksheet_xml(
            "Statistics",
            "GMJ Spinning Drop IFT — Statistics",
            statistics_rows,
            [
                12,
                10,
                18,
                17,
                17,
                18,
                13,
            ],
        )

        workbook = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships">'
            '<sheets>'
            '<sheet name="Measurement Summary" sheetId="1" r:id="rId1"/>'
            '<sheet name="Stage Samples" sheetId="2" r:id="rId2"/>'
            '<sheet name="Statistics" sheetId="3" r:id="rId3"/>'
            '</sheets>'
            '</workbook>'
        )

        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" '
            'Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" '
            'Target="worksheets/sheet3.xml"/>'
            '<Relationship Id="rId4" '
            'Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/styles" '
            'Target="styles.xml"/>'
            '</Relationships>'
        )

        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>'
        )

        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/>'
            '<Default Extension="xml" '
            'ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet3.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.styles+xml"/>'
            '</Types>'
        )

        # Styles:
        # 1 title, 2 metadata, 3 table header.
        # 8/9 body odd/even.
        # Subsequent pairs add restrained numeric formats to body cells.
        styles = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">'
            '<numFmts count="4">'
            '<numFmt numFmtId="164" formatCode="0.000"/>'
            '<numFmt numFmtId="165" formatCode="0.000000"/>'
            '<numFmt numFmtId="166" formatCode="0.000000E+00"/>'
            '<numFmt numFmtId="167" formatCode="0.00"/>'
            '</numFmts>'
            '<fonts count="4">'
            '<font><sz val="10"/><name val="Calibri"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="15"/>'
            '<name val="Calibri"/></font>'
            '<font><color rgb="FF405466"/><sz val="9"/>'
            '<name val="Calibri"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="10"/>'
            '<name val="Calibri"/></font>'
            '</fonts>'
            '<fills count="6">'
            '<fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FF23465C"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFEAF1F5"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FF2E6F8E"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFF5F8FA"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '</fills>'
            '<borders count="2">'
            '<border><left/><right/><top/><bottom/><diagonal/></border>'
            '<border>'
            '<left style="thin"><color rgb="FFD4DEE4"/></left>'
            '<right style="thin"><color rgb="FFD4DEE4"/></right>'
            '<top style="thin"><color rgb="FFD4DEE4"/></top>'
            '<bottom style="thin"><color rgb="FFD4DEE4"/></bottom>'
            '<diagonal/>'
            '</border>'
            '</borders>'
            '<cellStyleXfs count="1">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            '</cellStyleXfs>'
            '<cellXfs count="26">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
            'applyFont="1" applyFill="1" applyAlignment="1">'
            '<alignment horizontal="left" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" '
            'applyFont="1" applyFill="1" applyAlignment="1">'
            '<alignment horizontal="left" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" '
            'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center" wrapText="1"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" '
            'applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="164" fontId="0" fillId="5" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="165" fontId="0" fillId="5" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="166" fontId="0" fillId="5" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            '<xf numFmtId="167" fontId="0" fillId="5" borderId="1" xfId="0" '
            'applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/>'
            '</xf>'
            # Styles 18..25 are aliases retained so future small formatting
            # adjustments can be made without disturbing existing IDs.
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0"/>'
            '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0"/>'
            '<xf numFmtId="164" fontId="0" fillId="5" borderId="1" xfId="0"/>'
            '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0"/>'
            '<xf numFmtId="165" fontId="0" fillId="5" borderId="1" xfId="0"/>'
            '<xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0"/>'
            '<xf numFmtId="167" fontId="0" fillId="5" borderId="1" xfId="0"/>'
            '</cellXfs>'
            '<cellStyles count="1">'
            '<cellStyle name="Normal" xfId="0" builtinId="0"/>'
            '</cellStyles>'
            '</styleSheet>'
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:

            archive.writestr(
                "[Content_Types].xml",
                content_types,
            )

            archive.writestr(
                "_rels/.rels",
                root_rels,
            )

            archive.writestr(
                "xl/workbook.xml",
                workbook,
            )

            archive.writestr(
                "xl/styles.xml",
                styles,
            )

            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                workbook_rels,
            )

            archive.writestr(
                "xl/worksheets/sheet1.xml",
                summary_xml,
            )

            archive.writestr(
                "xl/worksheets/sheet2.xml",
                samples_xml,
            )

            archive.writestr(
                "xl/worksheets/sheet3.xml",
                statistics_xml,
            )

    def _measurement_table_rows(
        self,
    ) -> list[list[Any]] | None:

        if not self.front_panel:
            return None

        expected_headers = [
            "RPM",
            "Dia (px)",
            "Dia (mm)",
            "kg/m3",
            "w²",
            "r³",
            "IFT N/m",
            "IFT mN/m",
        ]

        for value in (
            self.front_panel.values.values()
        ):

            if (
                isinstance(
                    value,
                    list,
                )
                and len(
                    value
                ) >= 2
                and isinstance(
                    value[0],
                    list,
                )
                and value[0]
                == expected_headers
            ):
                return [
                    list(
                        row
                    )
                    for row
                    in value
                    if isinstance(
                        row,
                        list,
                    )
                ]

        return None

    def _measurement_workbook_rows(
        self,
    ) -> tuple[
        list[list[Any]],
        list[list[Any]],
        list[list[Any]],
    ] | None:
        """
        Build the three workbook tables from the current 10-sample runtime
        records. Falls back to the visible summary table if detailed records
        are unavailable, preserving export reliability.
        """

        table_rows = (
            self._measurement_table_rows()
        )

        if (
            table_rows is None
            or len(
                table_rows
            ) <= 1
        ):
            return None

        summary_headers = [
            "RPM",
            "Avg Dia (px)",
            "Avg Dia (mm)",
            "Δρ (kg/m³)",
            "ω²",
            "r³",
            "IFT (N/m)",
            "IFT (mN/m)",
            "Std Dev (px)",
            "CV (%)",
        ]

        sample_headers = [
            "RPM",
            "Sample",
            "Dia (px)",
            "Dia (mm)",
            "Scale Factor (mm/px)",
            "Capture File",
        ]

        statistics_headers = [
            "RPM",
            "N",
            "Mean Dia (px)",
            "Min Dia (px)",
            "Max Dia (px)",
            "Std Dev (px)",
            "CV (%)",
        ]

        detailed = getattr(
            self.runtime,
            "gmj_stage_measurements",
            None,
        )

        summary_rows: list[list[Any]] = [
            summary_headers
        ]

        sample_rows: list[list[Any]] = [
            sample_headers
        ]

        statistics_rows: list[list[Any]] = [
            statistics_headers
        ]

        if isinstance(
            detailed,
            list,
        ) and detailed:

            for record in detailed:

                if not isinstance(
                    record,
                    dict,
                ):
                    continue

                summary = record.get(
                    "summary_row"
                )

                stats = record.get(
                    "statistics"
                )

                samples = record.get(
                    "samples"
                )

                if (
                    not isinstance(
                        summary,
                        list,
                    )
                    or len(
                        summary
                    ) < 8
                    or not isinstance(
                        stats,
                        dict,
                    )
                ):
                    continue

                summary_rows.append(
                    [
                        summary[0],
                        summary[1],
                        summary[2],
                        summary[3],
                        summary[4],
                        summary[5],
                        summary[6],
                        summary[7],
                        stats.get(
                            "std_dev_diameter_px",
                            "",
                        ),
                        stats.get(
                            "cv_percent",
                            "",
                        ),
                    ]
                )

                statistics_rows.append(
                    [
                        summary[0],
                        int(
                            round(
                                float(
                                    stats.get(
                                        "n",
                                        0,
                                    )
                                )
                            )
                        ),
                        stats.get(
                            "mean_diameter_px",
                            "",
                        ),
                        stats.get(
                            "min_diameter_px",
                            "",
                        ),
                        stats.get(
                            "max_diameter_px",
                            "",
                        ),
                        stats.get(
                            "std_dev_diameter_px",
                            "",
                        ),
                        stats.get(
                            "cv_percent",
                            "",
                        ),
                    ]
                )

                if isinstance(
                    samples,
                    list,
                ):

                    if len(sample_rows) > 1:
                        sample_rows.append(
                            ["", "", "", "", "", ""]
                        )

                    for sample in samples:

                        if not isinstance(
                            sample,
                            dict,
                        ):
                            continue

                        sample_rows.append(
                            [
                                sample.get(
                                    "rpm",
                                    summary[0],
                                ),
                                sample.get(
                                    "sample",
                                    "",
                                ),
                                sample.get(
                                    "diameter_px",
                                    "",
                                ),
                                sample.get(
                                    "diameter_mm",
                                    "",
                                ),
                                sample.get(
                                    "scale_factor_mm_per_px",
                                    "",
                                ),
                                sample.get(
                                    "capture_file",
                                    "",
                                ),
                            ]
                        )

        # Fallback: preserve a valid summary export even if detailed runtime
        # records are unavailable for any reason.
        if len(
            summary_rows
        ) == 1:

            for row in table_rows[
                1:
            ]:

                if len(
                    row
                ) < 8:
                    continue

                summary_rows.append(
                    [
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        "",
                        "",
                    ]
                )

        return (
            summary_rows,
            sample_rows,
            statistics_rows,
        )

    def _next_measurement_export_path(
        self,
    ) -> Path:
        """
        Return the next non-overwriting Excel path for this app session.

        Active session:
            Measurements/spinning_drop_run_001.xlsx
            Measurements/spinning_drop_run_002.xlsx

        Measurements are written only inside the active session.
        """

        if self.session_root is None:
            raise RuntimeError(
                "Measurement export requires an active session"
            )

        folder = session_measurements_dir(
            self.session_root
        )

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        counter = (
            self._measurement_run_counter
            + 1
        )

        while True:
            destination = (
                folder
                / (
                    "spinning_drop_run_"
                    f"{counter:03d}.xlsx"
                )
            )

            if not destination.exists():
                return destination

            counter += 1

    def _export_measurement_table(
        self,
    ) -> None:

        if (
            not self._measurement_run_active
            or self._measurement_exported
        ):
            return

        workbook_rows = (
            self._measurement_workbook_rows()
        )

        if workbook_rows is None:
            return

        (
            summary_rows,
            sample_rows,
            statistics_rows,
        ) = workbook_rows

        destination = (
            self._next_measurement_export_path()
        )

        mode_label = (
            "Standard"
            if self.operating_mode
            == "standard"
            else (
                "Manual"
                if self.operating_mode
                == "manual"
                else "Other"
            )
        )

        try:

            self._write_measurement_xlsx(
                summary_rows,
                sample_rows,
                statistics_rows,
                destination,
                session_id=self.session_id,
                mode_label=mode_label,
            )

        except OSError as exc:

            self.log(
                "EXPORT ERROR "
                + str(
                    exc
                )
            )

            return

        self._measurement_exported = True
        self._measurement_run_active = False

        try:
            self._measurement_run_counter = int(
                destination.stem.rsplit(
                    "_",
                    1,
                )[1]
            )
        except (
            IndexError,
            ValueError,
        ):
            self._measurement_run_counter += 1

        self.log(
            "EXPORTED "
            + str(
                destination
            )
        )

    # ============================================================
    # RUN
    # ============================================================

    def run_once(
        self,
        schedule_next: bool = False,
    ) -> None:

        if self.controller.running:

            self.status_var.set(
                "Execution is already running"
            )

            return

        controls = (
            self.front_panel.control_values()
            if self.front_panel
            else {}
        )

        run_graph = (
            self.project.vis[
                self.current_vi_id
            ].graph
        )

        self.controller.start(
            run_graph,
            controls,
            self.project,
            self.current_vi_id,
            continuous=schedule_next,
            debug=bool(
                self.breakpoints
                or self.probes
            ),
            interval=0.060,
            breakpoints=self.breakpoints,
            probes=self.probes,
        )

        self.status_var.set(
            "Execution started"
        )

    def _analysis_snapshot_worker_loop(
        self,
    ) -> None:
        """
        Render queued Analysis PNG files away from the Tk/UI thread.

        Every job already contains a frozen copy of the values and chart data
        belonging to one raw stage sample.
        """

        while True:

            job = self._analysis_snapshot_jobs.get()

            try:
                snapshot_data, output_path = job

                PanelDesigner.render_analysis_snapshot(
                    snapshot_data,
                    output_path,
                )

            except Exception:
                # Analysis export must never stop motor/runtime/UI processing.
                # task_done() below also guarantees close_app cannot wait
                # forever on a failed image.
                pass

            finally:
                self._analysis_snapshot_jobs.task_done()

    def _capture_pending_analysis_snapshot(
        self,
    ) -> None:
        """
        Capture at most one queued analysis snapshot after the latest
        Front Panel result has been rendered.

        The runtime queues one request for each saved stage image, so the
        analysis PNG follows the same RPM/sample sequence as the 10 raw images.
        """

        if (
            self.front_panel is None
            or self.session_root is None
        ):
            return

        requests = getattr(
            self.runtime,
            "gmj_analysis_capture_requests",
            None,
        )

        if (
            not isinstance(
                requests,
                list,
            )
            or not requests
        ):
            return

        request = requests.pop(
            0
        )

        try:
            rpm = int(
                round(
                    float(
                        request[
                            "rpm"
                        ]
                    )
                )
            )

            sample_index = int(
                request[
                    "sample_index"
                ]
            )

            capture_file = Path(
                str(
                    request[
                        "capture_file"
                    ]
                )
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return

        output_dir = (
            session_analysis_rpm_dir(
                self.session_root,
                rpm,
            )
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        raw_name = (
            capture_file.stem
        )

        expected_prefix = (
            f"stage_{rpm}rpm_"
        )

        suffix = (
            raw_name[
                len(
                    expected_prefix
                ):
            ]
            if raw_name.startswith(
                expected_prefix
            )
            else (
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                f"{sample_index:03d}"
            )
        )

        output_path = (
            output_dir
            / (
                f"analysis_{rpm}rpm_"
                f"{suffix}.png"
            )
        )

        display_values: dict[
            str,
            Any,
        ] = {}

        display_frame = request.get(
            "display_frame"
        )
        display_wire_profile = request.get(
            "display_wire_profile"
        )

        if display_frame is not None:
            display_values[
                "wire_picture"
            ] = display_frame

        if isinstance(
            display_wire_profile,
            list,
        ):
            display_values[
                "wire_chart"
            ] = display_wire_profile

        if display_values:
            # Visible update for this exact saved sample. It happens before
            # freeze_analysis_snapshot(), so Analysis PNG #n sees the same
            # Picture Comparison / Grafik Kawat state as sample #n.
            self.front_panel.update_values(
                display_values
            )
            self._stage_display_override_active = True

        snapshot_data = (
            self.front_panel.freeze_analysis_snapshot()
        )

        if snapshot_data is None:
            return

        self._analysis_snapshot_jobs.put(
            (
                snapshot_data,
                output_path,
            )
        )

    # ============================================================
    # APPLY RESULT
    # ============================================================

    def _apply_result(
        self,
        result: Any,
    ) -> None:

        self.canvas.set_statuses(
            result.statuses
        )

        if self.front_panel:

            if self.operating_mode in (
                "standard",
                "manual",
            ):
                if result.values.get(
                    "oil_picture"
                ) is not None:
                    self._pre_run_camera_ready = True
                    self._hardware_camera_connected = True

                if self._pre_run_positive_number(
                    result.values.get(
                        "scale_display"
                    )
                ):
                    self._pre_run_calibration_ready = True

                # Serial reader returns a normal telemetry/error payload when
                # the active Arduino session is healthy. Any runtime error
                # that names the serial/Arduino path clears this indicator.
                serial_error = any(
                    (
                        "serial" in str(error).lower()
                        or "arduino" in str(error).lower()
                        or "com" in str(error).lower()
                    )
                    for error in result.errors
                )

                if serial_error:
                    self._hardware_arduino_connected = False
                elif self.controller.running:
                    self._hardware_arduino_connected = True

                self._refresh_hardware_status_dashboard()

            # Spinning-drop Standard / Manual Mode:
            # Motor START/STOP is controlled by the operator.
            #
            # Runtime results can contain a stale copy of the Motor
            # boolean because graph execution is asynchronous. Do not
            # pass that key back into the Front Panel in either mode.
            if self.operating_mode in (
                "standard",
                "manual",
            ):

                panel_values = dict(
                    result.values
                )

                panel_values.pop(
                    "motor",
                    None,
                )

                # Capture Reference is operator-controlled and momentary.
                # Do not let a stale runtime True repaint the indicator
                # green for a second time after the capture completes.
                panel_values.pop(
                    "capture_wire",
                    None,
                )

                if self._stage_display_override_active:
                    panel_values.pop(
                        "wire_picture",
                        None,
                    )
                    panel_values.pop(
                        "wire_chart",
                        None,
                    )

                self.front_panel.update_values(
                    panel_values
                )

            else:

                self.front_panel.update_values(
                    result.values
                )

            if self.operating_mode in (
                "standard",
                "manual",
            ):
                self._capture_pending_analysis_snapshot()

            # Capture Reference momentary reset:
            # reset only after this completed runtime result proves
            # that capture_wire=True was actually processed by the graph.
            if (
                self._capture_reference_reset_pending
                and bool(
                    result.values.get(
                        "capture_wire",
                        False,
                    )
                )
            ):

                self.front_panel.sync_control_value_from_model(
                    "capture_wire",
                    False,
                )

                self._capture_reference_reset_pending = False

                if self.controller.running:
                    self.controller.update_controls(
                        self.front_panel.control_values()
                    )

                self.front_panel.redraw()

            # Spinning-drop normal completion:
            # when the final 6000-RPM stage is reached, keep the UI
            # consistent with the Arduino's physical autostop by
            # returning the Motor control from START to STOP.
            if (
                "MAX_RPM_REACHED"
                in result.values.values()
                and bool(
                    self.front_panel.values.get(
                        "motor",
                        False,
                    )
                )
            ):

                self._export_measurement_table()

                self.front_panel.sync_control_value_from_model(
                    "motor",
                    False,
                )

                self._last_motor_control = False

                if self.controller.running:

                    self.controller.update_controls(
                        self.front_panel.control_values()
                    )

                self.front_panel.redraw()

        for line in result.logs:

            self.log(
                "LOG "
                + line
            )

        for error in result.errors:

            self.log(
                "ERROR "
                + error
            )

        if result.errors:

            self.status_var.set(
                "Execution failed: "
                f"{len(result.errors)} "
                "error(s)"
            )

        else:

            self.status_var.set(
                "Executed "
                f"{len(result.values)} "
                "node(s) successfully"
            )

    # ============================================================
    # POLL RUNTIME
    #
    # IMPORTANT:
    # Only newest runtime result is rendered.
    # ============================================================

    def _poll_runtime(
        self,
    ) -> None:

        self._runtime_poll_after_id = None

        # During a mode change the old workspace is being torn down.
        # Do not touch or reschedule UI widgets from that workspace.
        # _complete_startup() starts a fresh poll loop for the new mode.
        if self._mode_switch_in_progress:
            return

        events = (
            self.controller.drain_events()
        )

        # ========================================================
        # Drain ALL runtime events.
        #
        # But for result events keep only newest payload.
        # ========================================================

        for event in events:

            if (
                event.kind == "result"
                and event.payload
                is not None
            ):

                self._latest_runtime_result = (
                    event.payload
                )

                continue

            # Non-result events still appear in debugger.
            self.trace_tree.insert(
                "",
                "end",
                values=(
                    event.sequence,
                    event.kind,
                    event.node_id
                    or "",
                    event.value_preview
                    or event.message,
                ),
            )

        # ========================================================
        # Keep debugger trace bounded
        # ========================================================

        children = (
            self.trace_tree.get_children()
        )

        if len(children) > 1000:

            self.trace_tree.delete(
                *children[:100]
            )

        # ========================================================
        # GRADUAL STOP COMPLETION
        # ========================================================
        # Arduino owns the soft ramp. Keep runtime alive while RPM ramps
        # down so telemetry remains available. Once firmware confirms the
        # motor has actually stopped, perform the existing global stop.
        if self._gradual_stop_in_progress:
            session = self.controller.session

            gradual_complete = bool(
                session is not None
                and session.state.get(
                    self._gradual_stop_complete_key,
                    False,
                )
            )

            if gradual_complete:
                self._gradual_stop_in_progress = False
                self.stop()
                self.status_var.set(
                    "Gradual stop completed; global execution stopped"
                )

        # ========================================================
        # GLOBAL STOP MOMENTARY RESET
        # ========================================================
        # A Front Panel Global STOP click remains visibly active until
        # RunController.running becomes False, which means the worker thread
        # has exited and its finally block has closed runtime resources.
        if (
            self._global_stop_reset_pending
            and not self.controller.running
            and (
                time.monotonic()
                - self._global_stop_indicator_started_at
            )
            >= self._global_stop_indicator_min_visible_s
        ):
            if self.front_panel:
                self.front_panel.sync_control_value_from_model(
                    "global_stop",
                    False,
                )
                self.front_panel.redraw()

            self._global_stop_reset_pending = False
            self._global_stop_indicator_started_at = 0.0

        # ========================================================
        # Front Panel refresh throttling
        # ========================================================

        now = time.monotonic()

        should_update = (
            self._latest_runtime_result
            is not None
            and (
                now
                - self._last_runtime_ui_update
            )
            >= self._runtime_ui_interval
        )

        if should_update:

            result = (
                self._latest_runtime_result
            )

            # Remove pending result BEFORE redraw.
            #
            # If a newer result arrives during UI redraw,
            # it remains available for next refresh.
            self._latest_runtime_result = None

            self._last_runtime_ui_update = (
                now
            )

            self._apply_result(
                result
            )

        # Poll queue frequently so the 77 ms Front Panel target is not
        # quantized by a coarse 30 ms scheduler step. The previous 30 ms
        # polling could turn a nominal 77 ms UI interval into roughly
        # 90-110+ ms in practice once redraw time was included.
        self._runtime_poll_after_id = self.after(
            10,
            self._poll_runtime,
        )

    # ============================================================
    # CONTINUOUS
    # ============================================================

    def toggle_continuous(
        self,
    ) -> None:

        if self.continuous:

            self.stop_continuous()
            return

        self.continuous = True

        # If Stop Continuous was used previously, the runtime is
        # intentionally still alive so the camera can remain live.
        # Re-enter Continuous mode without starting a second worker.
        if self.controller.running:

            self.run_button.configure(
                text="Stop Continuous"
            )

            self.status_var.set(
                "Continuous execution resumed"
            )

            return

        # Remove any stale UI result.
        self._latest_runtime_result = None

        self._last_runtime_ui_update = 0.0

        # A new runtime must prove fresh camera/calibration readiness.
        self._pre_run_camera_ready = False
        self._pre_run_calibration_ready = False
        self._hardware_camera_connected = False
        self._hardware_arduino_connected = False
        self._refresh_hardware_status_dashboard()

        self.runtime.reset()

        self.run_button.configure(
            text="Stop Continuous"
        )

        self.status_var.set(
            "Continuous execution started"
        )

        self.run_once(
            True
        )

    # ============================================================
    # STOP CONTROL
    # ============================================================

    def _set_motor_stopped(
        self,
    ) -> None:

        self._export_measurement_table()

        if not self.front_panel:
            self._last_motor_control = False
            return

        self.front_panel.sync_control_value_from_model(
            "motor",
            False,
        )

        self._last_motor_control = False

        # Push Motor=False to the active runtime so the serial reader
        # performs its normal STOP transition. During Stop Continuous
        # the camera runtime intentionally remains alive.
        if self.controller.running:

            self.controller.update_controls(
                self.front_panel.control_values()
            )

        self.front_panel.redraw()

    def stop_continuous(
        self,
    ) -> None:

        # Soft stop:
        # motor/measurement STOP while camera stays connected/live.
        self._set_motor_stopped()

        self.continuous = False

        # Intentionally do NOT cancel the RunController here.
        self._latest_runtime_result = None

        self.run_button.configure(
            text="Continuous"
        )

        self.status_var.set(
            "Continuous measurement stopped; camera remains live"
        )

    # ============================================================
    # GRADUAL STOP
    # ============================================================

    def stop_gradually(
        self,
    ) -> None:

        # If execution is already stopped, there is nothing to ramp.
        if not self.controller.running:
            self.status_var.set(
                "Execution is not running"
            )
            return

        # If the motor is already STOP, no ramp is needed. Finish with
        # the existing global stop so camera/serial resources close too.
        motor_running = bool(
            self.front_panel
            and self.front_panel.values.get(
                "motor",
                False,
            )
        )

        if not motor_running:
            self.stop()
            self.status_var.set(
                "Motor already stopped; global execution stopped"
            )
            return

        if self._gradual_stop_in_progress:
            self.status_var.set(
                "Gradual stop already in progress"
            )
            return

        session = self.controller.session

        if session is None:
            self.status_var.set(
                "Gradual stop unavailable: runtime session is not active"
            )
            return

        # Do NOT set Motor=False here. Keeping run=True prevents the
        # existing handlers from issuing the immediate STOP command.
        # The handler sees this session request and sends SOFT_STOP instead.
        session.state[
            self._gradual_stop_request_key
        ] = True

        session.state[
            self._gradual_stop_complete_key
        ] = False

        self._gradual_stop_in_progress = True

        self.status_var.set(
            "Gradual stop requested; RPM is ramping down"
        )

    # ============================================================
    # GLOBAL STOP
    # ============================================================

    def stop(
        self,
    ) -> None:

        # Hard/global STOP always wins, including while a gradual stop
        # is in progress. Cancellation safe-stop still sends STOP.
        self._gradual_stop_in_progress = False

        # Global stop:
        # motor STOP + Motor indicator STOP + terminate runtime.
        # RunController cancellation closes camera/serial resources.
        self._set_motor_stopped()

        self.continuous = False

        self.controller.stop()

        self._pre_run_camera_ready = False
        self._pre_run_calibration_ready = False
        self._hardware_camera_connected = False
        self._hardware_arduino_connected = False
        self._refresh_hardware_status_dashboard()

        # Jangan render frame lama setelah execution dihentikan.
        self._latest_runtime_result = None

        self.run_button.configure(
            text="Continuous"
        )

        self.status_var.set(
            "Global execution stopped"
        )

    # ============================================================
    # DEBUG
    # ============================================================

    def pause_run(
        self,
    ) -> None:

        self.controller.pause()

        self.status_var.set(
            "Execution pause requested"
        )

    def resume_run(
        self,
    ) -> None:

        self.controller.resume()

        self.status_var.set(
            "Execution resumed"
        )

    def step_run(
        self,
    ) -> None:

        self.controller.step()

        self.status_var.set(
            "Single step requested"
        )

    def show_front_panel(
        self,
    ) -> None:

        self.workspace.select(
            0
        )

    # ============================================================
    # NEW PROJECT
    # ============================================================

    def new_project(
        self,
    ) -> None:

        if not self._confirm_discard():
            return

        self.stop()

        self.path = None

        self.undo_stack.clear()
        self.redo_stack.clear()

        self.project = Project()

        self.current_vi_id = (
            self.project.main_vi
        )

        self._replace_graph(
            self.project.main.graph
        )

        self._refresh_vi_list()

        self.dirty = False

        self._update_title()

        self.log(
            "New project created"
        )

    # ============================================================
    # OPEN PROJECT
    # ============================================================

    def open_project(
        self,
    ) -> None:

        if not self._confirm_discard():
            return

        path = (
            filedialog.askopenfilename(
                parent=self,
                title="Open Project",
                filetypes=(
                    (
                        "PyLabView Project",
                        "*.json",
                    ),
                    (
                        "JSON",
                        "*.json",
                    ),
                    (
                        "All Files",
                        "*.*",
                    ),
                ),
            )
        )

        if not path:
            return

        try:

            project = (
                load_project(
                    path
                )
            )

        except (
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:

            messagebox.showerror(
                "Open failed",
                str(exc),
                parent=self,
            )

            return

        self.stop()

        migrated = bool(
            project.migration_report
        )

        self.path = (
            None
            if migrated
            else Path(
                path
            )
        )

        self.undo_stack.clear()
        self.redo_stack.clear()

        self.project = project

        self.current_vi_id = (
            project.main_vi
        )

        self._replace_graph(
            project.main.graph
        )

        self._refresh_vi_list()

        self.dirty = migrated

        self._update_title()

        self.log(
            f"Opened {path}"
        )

        for line in (
            project.migration_report
        ):

            self.log(
                "MIGRATION "
                + line
            )

        if migrated:

            self.status_var.set(
                "Legacy project migrated in memory; "
                "Save will write a new v3 file"
            )

    # ============================================================
    # SAVE PROJECT
    # ============================================================

    def save_project(
        self,
    ) -> bool:

        if self.path is None:

            return (
                self.save_project_as()
            )

        try:

            save_project(
                self.project,
                self.path,
            )

        except (
            OSError,
            ValueError,
            TypeError,
        ) as exc:

            messagebox.showerror(
                "Save failed",
                str(exc),
                parent=self,
            )

            return False

        self.dirty = False

        self._update_title()

        self.status_var.set(
            f"Saved {self.path}"
        )

        return True

    def save_project_as(
        self,
    ) -> bool:

        path = (
            filedialog.asksaveasfilename(
                parent=self,
                title="Save Project",
                defaultextension=".json",
                initialfile=(
                    self.path.name
                    if self.path
                    else "project.json"
                ),
                filetypes=(
                    (
                        "PyLabView Project",
                        "*.json",
                    ),
                    (
                        "All Files",
                        "*.*",
                    ),
                ),
            )
        )

        if not path:
            return False

        destination = Path(
            path
        )

        try:

            candidate = (
                Project.from_dict(
                    self.project.to_dict()
                )
            )

            candidate.name = (
                destination.stem
            )

            save_project(
                candidate,
                destination,
            )

        except (
            OSError,
            ValueError,
            TypeError,
        ) as exc:

            messagebox.showerror(
                "Save failed",
                str(exc),
                parent=self,
            )

            return False

        self.path = destination

        self.project.name = (
            destination.stem
        )

        self.dirty = False

        self._update_title()

        self.status_var.set(
            f"Saved {self.path}"
        )

        return True

    # ============================================================
    # REPLACE GRAPH
    # ============================================================

    def _replace_graph(
        self,
        graph: Graph,
    ) -> None:

        self.current_diagram_id = None

        self.graph = graph

        if (
            self.current_vi_id
            in self.project.vis
        ):

            self.project.vis[
                self.current_vi_id
            ].graph = graph

            graph.project = (
                self.project
            )

        self.canvas.set_graph(
            graph
        )

        self.select_node(
            None
        )

        if self.front_panel:

            vi = (
                self.project.vis[
                    self.current_vi_id
                ]
            )

            vi.front_panel = (
                _normalized_panel(
                    vi.front_panel,
                    graph,
                )
            )

            self.front_panel.set_document(
                graph,
                vi.front_panel,
            )

    # ============================================================
    # DISCARD CONFIRMATION
    # ============================================================

    def _confirm_discard(
        self,
    ) -> bool:

        if not self.dirty:
            return True

        answer = (
            messagebox.askyesnocancel(
                "Unsaved changes",
                "Save changes before continuing?",
                parent=self,
            )
        )

        if answer is None:
            return False

        return (
            self.save_project()
            if answer
            else True
        )

    # ============================================================
    # CLOSE
    # ============================================================

    def close_app(
        self,
    ) -> None:

        if (
            self._closing
            or not self._confirm_discard()
        ):
            return

        self._closing = True

        self.stop()

        self.status_var.set(
            "Waiting for vendor calls to finish "
            "within their configured timeout..."
        )

        def finish() -> None:

            controller_done = (
                self.controller.join(
                    0
                )
            )

            analysis_done = (
                self._analysis_snapshot_jobs.unfinished_tasks
                == 0
            )

            if (
                controller_done
                and analysis_done
            ):

                self.destroy()

            else:

                self.after(
                    50,
                    finish,
                )

        finish()

    # ============================================================
    # TITLE
    # ============================================================

    def _update_title(
        self,
    ) -> None:

        name = (
            self.path.name
            if self.path
            else self.project.name
        )

        mode_label = (
            "Standard Mode"
            if self.operating_mode == "standard"
            else (
                "Manual RPM Mode"
                if self.operating_mode == "manual"
                else None
            )
        )

        self.title(
            f"{'*' if self.dirty else ''}"
            f"{name} "
            f"[{self.project.vis[self.current_vi_id].name}] "
            f"{'[' + mode_label + '] ' if mode_label else ''}"
            "- PyLabView Studio"
        )

    # ============================================================
    # VI LIST
    # ============================================================

    def _refresh_vi_list(
        self,
    ) -> None:

        if not hasattr(
            self,
            "vi_list",
        ):
            return

        self.vi_list.delete(
            0,
            "end",
        )

        self._vi_order = list(
            self.project.vis
        )

        for vi_id in (
            self._vi_order
        ):

            vi = (
                self.project.vis[
                    vi_id
                ]
            )

            self.vi_list.insert(
                "end",
                (
                    "* "
                    if vi_id
                    == self.project.main_vi
                    else "  "
                )
                + vi.name,
            )

        if (
            self.current_vi_id
            in self._vi_order
        ):

            index = (
                self._vi_order.index(
                    self.current_vi_id
                )
            )

            self.vi_list.selection_set(
                index
            )

    def _switch_vi_event(
        self,
        _event: tk.Event,
    ) -> None:

        selection = (
            self.vi_list.curselection()
        )

        if selection:

            self.switch_vi(
                self._vi_order[
                    selection[0]
                ]
            )

    def switch_vi(
        self,
        vi_id: str,
    ) -> None:

        if (
            vi_id
            == self.current_vi_id
            or vi_id
            not in self.project.vis
        ):
            return

        self.stop()

        self.current_vi_id = vi_id

        self._replace_graph(
            self.project.vis[
                vi_id
            ].graph
        )

        self._update_title()

    # ============================================================
    # VI MANAGEMENT
    # ============================================================

    def add_vi(
        self,
    ) -> None:

        name = simpledialog.askstring(
            "Add VI",
            "VI name:",
            parent=self,
        )

        if not name:
            return

        if (
            not name.strip()
            or any(
                vi.name
                == name.strip()
                for vi
                in self.project.vis.values()
            )
        ):

            messagebox.showerror(
                "Add VI",
                "VI name must be non-empty and unique",
                parent=self,
            )

            return

        self.checkpoint()

        try:

            vi = (
                self.project.add_vi(
                    name
                )
            )

        except ValueError as exc:

            messagebox.showerror(
                "Add VI",
                str(exc),
                parent=self,
            )

            return

        self.current_vi_id = (
            vi.id
        )

        self._replace_graph(
            vi.graph
        )

        self.changed()

        self._refresh_vi_list()

    def rename_vi(
        self,
    ) -> None:

        vi = (
            self.project.vis[
                self.current_vi_id
            ]
        )

        name = simpledialog.askstring(
            "Rename VI",
            "VI name:",
            initialvalue=vi.name,
            parent=self,
        )

        if not name:
            return

        if name.strip() == vi.name:
            return

        if (
            not name.strip()
            or any(
                item.name
                == name.strip()
                and item.id
                != vi.id
                for item
                in self.project.vis.values()
            )
        ):

            messagebox.showerror(
                "Rename VI",
                "VI name must be non-empty and unique",
                parent=self,
            )

            return

        self.checkpoint()

        try:

            self.project.rename_vi(
                vi.id,
                name,
            )

        except ValueError as exc:

            messagebox.showerror(
                "Rename VI",
                str(exc),
                parent=self,
            )

            return

        self.changed()
        self._refresh_vi_list()

    def delete_vi(
        self,
    ) -> None:

        vi_id = (
            self.current_vi_id
        )

        if (
            vi_id
            == self.project.main_vi
        ):

            messagebox.showerror(
                "Delete VI",
                "cannot delete main VI",
                parent=self,
            )

            return

        if not messagebox.askyesno(
            "Delete VI",
            (
                f"Delete "
                f"{self.project.vis[vi_id].name}?"
            ),
            parent=self,
        ):
            return

        self.checkpoint()

        try:

            self.project.delete_vi(
                vi_id
            )

        except ValueError as exc:

            messagebox.showerror(
                "Delete VI",
                str(exc),
                parent=self,
            )

            return

        self.current_vi_id = (
            self.project.main_vi
        )

        self._replace_graph(
            self.project.main.graph
        )

        self.changed()

        self._refresh_vi_list()

    def set_main_vi(
        self,
    ) -> None:

        if (
            self.current_vi_id
            == self.project.main_vi
        ):
            return

        self.checkpoint()

        self.project.set_main(
            self.current_vi_id
        )

        self.changed()

        self._refresh_vi_list()

    # ============================================================
    # CREATE SUBVI
    # ============================================================

    def create_subvi(
        self,
    ) -> None:

        choices = [
            vi
            for vi
            in self.project.vis.values()
            if vi.id
            != self.current_vi_id
        ]

        if not choices:

            messagebox.showinfo(
                "Create SubVI",
                "Add another VI first.",
                parent=self,
            )

            return

        name = simpledialog.askstring(
            "Create SubVI",
            "Target VI name:\n"
            + ", ".join(
                vi.name
                for vi
                in choices
            ),
            parent=self,
        )

        target = next(
            (
                vi
                for vi
                in choices
                if vi.name
                == name
            ),
            None,
        )

        if not target:

            if name is not None:

                messagebox.showerror(
                    "Create SubVI",
                    "Unknown VI name.",
                    parent=self,
                )

            return

        self.checkpoint()

        node = (
            self.graph.add_node(
                "subvi",
                100,
                100,
            )
        )

        node.label = (
            target.name
        )

        node.properties[
            "vi_id"
        ] = target.id

        self.changed()

        self.canvas.redraw()

    # ============================================================
    # STRUCTURES
    # ============================================================

    def _initialize_structure(
        self,
        node: Node,
    ) -> None:

        vi = (
            self.project.vis[
                self.current_vi_id
            ]
        )

        def identity_diagram(
            name: str,
            include_iteration: bool = False,
        ) -> tuple[
            str,
            Graph,
        ]:

            diagram_id = (
                f"{node.id}-{name}"
            )

            graph = Graph(
                f"{node.label} / {name}"
            )

            source = (
                graph.add_node(
                    "structure_input",
                    80,
                    100,
                )
            )

            source.properties[
                "name"
            ] = "value"

            output = (
                graph.add_node(
                    "structure_output",
                    360,
                    100,
                )
            )

            graph.connect(
                source.id,
                "out",
                output.id,
                "value",
            )

            if include_iteration:

                graph.add_node(
                    "iteration_terminal",
                    80,
                    220,
                )

            graph.project = (
                self.project
            )

            vi.subdiagrams[
                diagram_id
            ] = graph

            return (
                diagram_id,
                graph,
            )

        if node.type == "visual_case":

            node.properties[
                "true_diagram"
            ] = identity_diagram(
                "True"
            )[0]

            node.properties[
                "false_diagram"
            ] = identity_diagram(
                "False"
            )[0]

        else:

            node.properties[
                "body_diagram"
            ] = identity_diagram(
                "Body",
                True,
            )[0]

    def _clone_structure_properties(
        self,
        node_type: str,
        properties: dict[
            str,
            Any,
        ],
    ) -> dict[
        str,
        Any,
    ]:

        return (
            clone_structure_properties(
                self.project,
                self.current_vi_id,
                node_type,
                properties,
            )
        )

    def _delete_node_resources(
        self,
        node: Node,
    ) -> None:

        delete_owned_structure_diagrams(
            self.project,
            self.current_vi_id,
            node,
        )

    def open_structure(
        self,
    ) -> None:

        node_id = (
            self.canvas.selected_node
        )

        if (
            not node_id
            or node_id
            not in self.graph.nodes
        ):

            self.status_var.set(
                "Select a visual Case or "
                "For Loop structure"
            )

            return

        node = (
            self.graph.nodes[
                node_id
            ]
        )

        if node.type == "visual_case":

            choice = (
                messagebox.askyesno(
                    "Open Case Structure",
                    (
                        "Open True region?\n"
                        "Choose No for False."
                    ),
                    parent=self,
                )
            )

            diagram_id = str(
                node.properties.get(
                    (
                        "true_diagram"
                        if choice
                        else "false_diagram"
                    ),
                    "",
                )
            )

        elif node.type == "visual_for":

            diagram_id = str(
                node.properties.get(
                    "body_diagram",
                    "",
                )
            )

        else:

            self.status_var.set(
                "Selected node is not "
                "a visual structure"
            )

            return

        graph = (
            self.project.vis[
                self.current_vi_id
            ].subdiagrams.get(
                diagram_id
            )
        )

        if not graph:

            messagebox.showerror(
                "Open Structure",
                "Structure subdiagram is missing",
                parent=self,
            )

            return

        self.current_diagram_id = (
            diagram_id
        )

        self.graph = graph

        self.canvas.set_graph(
            graph
        )

        self.workspace.select(
            1
        )

        self.status_var.set(
            f"Editing subdiagram: {graph.name}"
        )

    def open_root_diagram(
        self,
    ) -> None:

        self.current_diagram_id = None

        self.graph = (
            self.project.vis[
                self.current_vi_id
            ].graph
        )

        self.canvas.set_graph(
            self.graph
        )

        self.workspace.select(
            1
        )

        self.status_var.set(
            "Editing root Block Diagram"
        )

    # ============================================================
    # BREAKPOINT / PROBE
    # ============================================================

    def toggle_breakpoint(
        self,
    ) -> None:

        node_id = (
            self.canvas.selected_node
        )

        if not node_id:

            self.status_var.set(
                "Select a node to toggle "
                "its breakpoint"
            )

            return

        if node_id in self.breakpoints:

            self.breakpoints.remove(
                node_id
            )

            state = "removed"

        else:

            self.breakpoints.add(
                node_id
            )

            state = "set"

        self.status_var.set(
            f"Breakpoint {state}: "
            f"{self.graph.nodes[node_id].label}"
        )

    def toggle_probe(
        self,
    ) -> None:

        wire = (
            self.canvas.selected_wire
        )

        if not wire:

            self.status_var.set(
                "Select a wire to toggle "
                "its probe"
            )

            return

        key = (
            f"{wire.source_node}:"
            f"{wire.source_port}->"
            f"{wire.target_node}:"
            f"{wire.target_port}"
        )

        if key in self.probes:

            self.probes.remove(
                key
            )

            state = "removed"

        else:

            self.probes.add(
                key
            )

            state = "set"

        self.status_var.set(
            f"Probe {state}: {key}"
        )

    # ============================================================
    # PLUGIN STATUS
    # ============================================================

    def show_plugins(
        self,
    ) -> None:

        statuses = (
            DEFAULT_PLUGIN_REGISTRY.discover()
        )

        lines = [
            (
                f"{item.plugin_id} "
                f"{item.version}: "
                f"{item.state}"
                f"{' - ' + item.message if item.message else ''}"
            )
            for item
            in statuses
        ]

        lines.append(
            "\nPlugins execute as trusted Python in this process; "
            "they are not sandboxed and are never auto-installed."
        )

        messagebox.showinfo(
            "Plugin Status",
            "\n".join(
                lines
            ),
            parent=self,
        )

    # ============================================================
    # DIAGNOSTICS
    # ============================================================

    def show_diagnostics(
        self,
    ) -> None:

        from .integrations.capabilities import (
            collect_diagnostics,
            collect_hardware_diagnostics_bounded,
            diagnostics_text,
        )

        dialog = tk.Toplevel(
            self
        )

        dialog.title(
            "Hardware / Integration Diagnostics"
        )

        dialog.transient(
            self
        )

        text = tk.Text(
            dialog,
            width=100,
            height=28,
            wrap="word",
            state="disabled",
        )

        text.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        results: Queue[
            tuple[
                int,
                Any,
            ]
        ] = Queue()

        generation = 0
        closed = False

        def render(
            diagnostics: Any,
        ) -> None:

            text.configure(
                state="normal"
            )

            text.delete(
                "1.0",
                "end",
            )

            text.insert(
                "end",
                diagnostics_text(
                    diagnostics
                ),
            )

            text.insert(
                "end",
                (
                    "\n\nHardware enumeration runs in a bounded "
                    "child process only after Refresh Hardware. "
                    "Physical hardware is not validated by this project."
                ),
            )

            text.configure(
                state="disabled"
            )

        def poll() -> None:

            if (
                closed
                or not dialog.winfo_exists()
            ):
                return

            try:

                while True:

                    (
                        item_generation,
                        diagnostics,
                    ) = (
                        results.get_nowait()
                    )

                    if (
                        item_generation
                        == generation
                    ):

                        render(
                            diagnostics
                        )

                        software_button.configure(
                            state="normal"
                        )

                        hardware_button.configure(
                            state="normal"
                        )

            except Empty:
                pass

            dialog.after(
                50,
                poll,
            )

        def refresh(
            hardware: bool = False,
        ) -> None:

            nonlocal generation

            generation += 1

            requested_generation = (
                generation
            )

            software_button.configure(
                state="disabled"
            )

            hardware_button.configure(
                state="disabled"
            )

            text.configure(
                state="normal"
            )

            text.delete(
                "1.0",
                "end",
            )

            text.insert(
                "end",
                "Collecting diagnostics...",
            )

            text.configure(
                state="disabled"
            )

            manifest = (
                self.project.extensions.get(
                    "runtime_target"
                )
                if hardware
                else None
            )

            def worker() -> None:

                diagnostics = (
                    collect_hardware_diagnostics_bounded(
                        timeout=10,
                        target_manifest=manifest,
                    )
                    if hardware
                    else collect_diagnostics(
                        refresh_hardware=False
                    )
                )

                results.put(
                    (
                        requested_generation,
                        diagnostics,
                    )
                )

            Thread(
                target=worker,
                name="pylabview-diagnostics",
                daemon=True,
            ).start()

        def close_dialog() -> None:

            nonlocal closed, generation

            closed = True
            generation += 1

            dialog.destroy()

        buttons = ttk.Frame(
            dialog
        )

        buttons.pack(
            fill="x",
            padx=8,
            pady=(
                0,
                8,
            ),
        )

        software_button = (
            ttk.Button(
                buttons,
                text="Refresh Software",
                command=lambda: (
                    refresh(
                        False
                    )
                ),
            )
        )

        software_button.pack(
            side="left"
        )

        hardware_button = (
            ttk.Button(
                buttons,
                text="Refresh Hardware",
                command=lambda: (
                    refresh(
                        True
                    )
                ),
            )
        )

        hardware_button.pack(
            side="left",
            padx=6,
        )

        ttk.Button(
            buttons,
            text="Close",
            command=close_dialog,
        ).pack(
            side="right"
        )

        dialog.protocol(
            "WM_DELETE_WINDOW",
            close_dialog,
        )

        poll()
        refresh(
            False
        )

    # ============================================================
    # VERILOG EXPORT
    # ============================================================

    def export_verilog(
        self,
    ) -> None:

        from .hdl import (
            HdlExportError,
            export_verilog,
        )

        try:

            source = (
                export_verilog(
                    self.graph,
                    self.graph.name,
                )
            )

        except HdlExportError as exc:

            messagebox.showerror(
                "Export Verilog",
                str(exc),
                parent=self,
            )

            return

        path = (
            filedialog.asksaveasfilename(
                parent=self,
                title="Export restricted HDL subset",
                defaultextension=".v",
                filetypes=(
                    (
                        "Verilog",
                        "*.v",
                    ),
                    (
                        "All Files",
                        "*.*",
                    ),
                ),
            )
        )

        if not path:
            return

        try:

            Path(
                path
            ).write_text(
                source,
                encoding="ascii",
            )

        except OSError as exc:

            messagebox.showerror(
                "Export Verilog",
                str(exc),
                parent=self,
            )

            return

        self.status_var.set(
            (
                f"Exported HDL subset to {path}; "
                "no FPGA bitstream was generated"
            )
        )

    # ============================================================
    # CONNECTOR
    # ============================================================

    def configure_connector(
        self,
    ) -> None:

        vi = (
            self.project.vis[
                self.current_vi_id
            ]
        )

        dialog = tk.Toplevel(
            self
        )

        dialog.title(
            "Connector Pane - "
            + vi.name
        )

        dialog.transient(
            self
        )

        dialog.grab_set()

        ttk.Label(
            dialog,
            text=(
                "Satu terminal per baris: "
                "direction,name,node_id,port,type\n"
                "Input wajib menunjuk output control yang unik; "
                "output menunjuk output node."
            ),
        ).pack(
            anchor="w",
            padx=10,
            pady=8,
        )

        text = tk.Text(
            dialog,
            width=75,
            height=14,
        )

        text.pack(
            fill="both",
            expand=True,
            padx=10,
        )

        for (
            direction,
            terminals,
        ) in (
            (
                "input",
                vi.connector_inputs,
            ),
            (
                "output",
                vi.connector_outputs,
            ),
        ):

            for term in terminals:

                text.insert(
                    "end",
                    (
                        f"{direction},"
                        f"{term.name},"
                        f"{term.node_id},"
                        f"{term.port},"
                        f"{term.data_type}\n"
                    ),
                )

        def apply() -> None:

            inputs: list[
                ConnectorTerminal
            ] = []

            outputs: list[
                ConnectorTerminal
            ] = []

            try:

                for line in (
                    text.get(
                        "1.0",
                        "end",
                    ).splitlines()
                ):

                    if not line.strip():
                        continue

                    (
                        direction,
                        name,
                        node_id,
                        port,
                        data_type,
                    ) = [
                        part.strip()
                        for part
                        in line.split(
                            ","
                        )
                    ]

                    if (
                        direction
                        not in (
                            "input",
                            "output",
                        )
                        or data_type
                        not in DATA_TYPES
                    ):

                        raise ValueError(
                            "direction/type connector "
                            "tidak valid"
                        )

                    (
                        inputs
                        if direction
                        == "input"
                        else outputs
                    ).append(
                        ConnectorTerminal(
                            name,
                            node_id,
                            port,
                            data_type,
                        )
                    )

                old_in = (
                    vi.connector_inputs
                )

                old_out = (
                    vi.connector_outputs
                )

                vi.connector_inputs = (
                    inputs
                )

                vi.connector_outputs = (
                    outputs
                )

                try:

                    self.project.validate_connectors()

                finally:

                    vi.connector_inputs = (
                        old_in
                    )

                    vi.connector_outputs = (
                        old_out
                    )

                valid_inputs = {
                    term.name
                    for term
                    in inputs
                }

                valid_outputs = {
                    term.name
                    for term
                    in outputs
                }

                input_types = {
                    term.name: term.data_type
                    for term
                    in inputs
                }

                output_types = {
                    term.name: term.data_type
                    for term
                    in outputs
                }

                affected: list[
                    tuple[
                        Graph,
                        Any,
                    ]
                ] = []

                for parent_vi in (
                    self.project.vis.values()
                ):

                    for parent_graph in (
                        parent_vi.graph,
                        *parent_vi.subdiagrams.values(),
                    ):

                        calls = {
                            node.id
                            for node
                            in parent_graph.nodes.values()
                            if (
                                node.type
                                == "subvi"
                                and node.properties.get(
                                    "vi_id"
                                )
                                == vi.id
                            )
                        }

                        for wire in (
                            parent_graph.wires
                        ):

                            invalid_source = (
                                wire.source_node
                                in calls
                                and (
                                    wire.source_port
                                    not in valid_outputs
                                    or not compatible(
                                        output_types[
                                            wire.source_port
                                        ],
                                        parent_graph.port_type(
                                            parent_graph.nodes[
                                                wire.target_node
                                            ],
                                            "in",
                                            wire.target_port,
                                        ),
                                    )
                                )
                            )

                            invalid_target = (
                                wire.target_node
                                in calls
                                and (
                                    wire.target_port
                                    not in valid_inputs
                                    or not compatible(
                                        parent_graph.port_type(
                                            parent_graph.nodes[
                                                wire.source_node
                                            ],
                                            "out",
                                            wire.source_port,
                                        ),
                                        input_types[
                                            wire.target_port
                                        ],
                                    )
                                )
                            )

                            if (
                                invalid_source
                                or invalid_target
                            ):

                                affected.append(
                                    (
                                        parent_graph,
                                        wire,
                                    )
                                )

            except (
                KeyError,
                StopIteration,
                ValueError,
                TypeError,
            ) as exc:

                messagebox.showerror(
                    "Connector Pane",
                    str(exc),
                    parent=dialog,
                )

                return

            if (
                affected
                and not messagebox.askyesno(
                    "Connector Pane",
                    (
                        "Perubahan ini akan menghapus "
                        f"{len(affected)} wire "
                        "yang tidak lagi valid. Lanjutkan?"
                    ),
                    parent=dialog,
                )
            ):
                return

            if (
                inputs == old_in
                and outputs == old_out
            ):

                dialog.destroy()
                return

            self.checkpoint()

            vi.connector_inputs = (
                inputs
            )

            vi.connector_outputs = (
                outputs
            )

            affected_by_graph: dict[
                Graph,
                set[int],
            ] = {}

            for (
                parent_graph,
                wire,
            ) in affected:

                affected_by_graph.setdefault(
                    parent_graph,
                    set(),
                ).add(
                    id(
                        wire
                    )
                )

            for (
                parent_graph,
                wire_ids,
            ) in affected_by_graph.items():

                parent_graph.wires = [
                    wire
                    for wire
                    in parent_graph.wires
                    if id(
                        wire
                    )
                    not in wire_ids
                ]

            self.changed()

            self.canvas.redraw()

            dialog.destroy()

        ttk.Button(
            dialog,
            text="Apply",
            command=apply,
        ).pack(
            pady=8
        )

    # ============================================================
    # VALIDATION
    # ============================================================

    def validate_current(
        self,
    ) -> None:

        errors = (
            self.runtime.validate(
                self.graph,
                self.project,
                self.current_vi_id,
            )
        )

        if errors:

            for error in errors:

                self.log(
                    "VALIDATION "
                    + error
                )

            self.status_var.set(
                f"Validation failed: "
                f"{len(errors)} error(s)"
            )

        else:

            self.status_var.set(
                "Validation successful"
            )

    # ============================================================
    # LOG
    # ============================================================

    def log(
        self,
        text: str,
    ) -> None:

        self.console.configure(
            state="normal"
        )

        self.console.insert(
            "end",
            text + "\n",
        )

        self.console.see(
            "end"
        )

        self.console.configure(
            state="disabled"
        )

    # ============================================================
    # HELP
    # ============================================================

    def show_help(
        self,
    ) -> None:

        messagebox.showinfo(
            "PyLabView Studio Help",
            (
                "Use the embedded Front Panel and Block Diagram tabs. "
                "In Panel Edit mode, drag items or resize from the lower-right "
                "handle; Operate mode changes controls.\n\n"
                "Double-click a library item to add it. "
                "Wire an output port to an input port. "
                "Select a visual structure and use Open Structure "
                "to edit its region.\n\n"
                "F6 runs continuously. Stop performs a global stop, while "
                "Stop Continuous stops the motor/measurement and keeps the camera live. "
                "Select a node for Breakpoint "
                "or a wire for Probe."
            ),
            parent=self,
        )

    # ============================================================
    # ABOUT
    # ============================================================

    def show_about(
        self,
    ) -> None:

        messagebox.showinfo(
            "About PyLabView Studio",
            (
                f"PyLabView Studio {__version__}\n\n"
                "An independent, educational Python dataflow environment. "
                "This project is not affiliated with, endorsed by, "
                "or a product of National Instruments. "
                "LabVIEW is a trademark of its respective owner."
            ),
            parent=self,
        )


# ================================================================
# MAIN
# ================================================================

def main() -> None:

    # Give Windows a stable application identity so the runtime taskbar
    # icon groups under GMJ Global Energy instead of the Python host.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "GMJ.GlobalEnergy.PyLabViewStudio"
        )

    except (AttributeError, OSError):
        pass

    app = StudioApp()

    app.mainloop()

if __name__ == "__main__":
    main()