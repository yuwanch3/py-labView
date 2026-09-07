# Changelog

All notable user-facing changes to PyLabView Studio are recorded here.

## [7.9.0] - 2026-09-07

### Added

- Added **Stop Bertahap** to both Standard Mode and Manual RPM Mode.
- Added firmware-side `SOFT_STOP` handling for gradual motor deceleration while preserving the existing immediate hard `STOP`.
- Added GMJ application branding for the startup window, main application window, Windows taskbar, and packaged executable.
- Added GMJ runtime PNG icon and Windows executable ICO asset.

### Changed

- Improved camera frame freshness by using the latest available network frame instead of allowing stale buffered frames to accumulate.
- Improved serial telemetry responsiveness by reading only currently available serial bytes and preserving incomplete lines between reads.
- Improved Front Panel runtime rendering for Picture Oil, Picture Comparison, tables, RPM, PWM, timers, and WIFI indicators.
- Reduced unnecessary Front Panel status redraws when displayed status values have not changed.
- Gradual stopping now remains firmware-owned so Python does not implement RPM ramp timing.
- Manual RPM control preserves PID state correctly during active operation and gradual stopping.
- Windows executable packaging now embeds the GMJ `.ico` resource through both PyInstaller build specifications.
- Application, Windows file metadata, README, and architecture documentation were updated for release 7.9.0.

### Fixed

- Fixed Manual RPM PID reset behavior that could interfere with convergence to the requested target RPM.
- Fixed excessive serial-read blocking that could cause approximately multi-second telemetry delay.
- Fixed cumulative scaling behavior in persistent Front Panel elements during repeated zoom operations.
- Fixed Front Panel zoom compatibility with viewport unit-test fakes.
- Reduced stale camera-frame behavior during network/DroidCam operation.
- Preserved immediate hard-stop behavior even when Stop Bertahap is already active.

### Cleanup

- Removed temporary runtime, camera, Front Panel, UI timing, and benchmark diagnostic logging from production application code.
- Kept local benchmark tooling outside the tracked production source tree.

### Validation

- Full automated test suite passed with **275 tests**.
- Standard Mode and Manual RPM Mode retained separate operating workflows.
- Project schema remains version 3.
- Existing schema-v3 projects remain compatible.
- V1/v2 migration behavior remains unchanged.

## [7.8.3] - 2026-09-02

### Added

- Added **Standard Mode** and **Manual RPM Mode** startup selection with separate spinning-drop project templates.
- Added `spinning_drop_manual.py` and Manual RPM node support so the operator can request a target RPM up to 6000 RPM while PWM remains controlled automatically by the Arduino PID.
- Added dual-mode Arduino protocol support for `MODE:STANDARD`, `MODE:MANUAL`, `SET_TARGET:<rpm>`, `START`, and `STOP`, including `TARGET_REACHED:<rpm>` handling for Manual Mode.
- Added automatic copying of the default Standard and Manual example projects into `Documents\GMJ PyLabView\Examples` when they are missing, without overwriting existing user copies.
- Added centralized application path handling for bundled resources and writable user data.
- Added writable user-data directories under `Documents\GMJ PyLabView` for `Captures`, `Measurement Exports`, `Examples`, and `Projects`.
- Added automatic Excel `.xlsx` export for spinning-drop measurement results.
- Added application-wide Global Stop behavior shared by Standard and Manual modes.
- Added a single full-profile Windows release workflow that produces `PyLabViewStudio.exe` and its SHA-256 checksum.

### Changed

- Standard Mode keeps the established automatic 1000 → 2000 → 3000 → 4000 → 5000 → 6000 RPM sequence while Manual Mode is implemented separately so the Standard workflow remains unchanged.
- Manual RPM operation uses a firmware-side soft ramp and PID control; intermediate ramp targets are not logged as completed measurement stages.
- Capture Reference now behaves as a momentary operator action: one activation captures/updates the reference and then returns to the inactive state.
- Stop Continuous now stops the active measurement/motor run while preserving the intended camera workflow; Global Stop terminates the active motor/controller/runtime path.
- Startup asset and example-project resolution now uses bundled-resource helpers instead of depending on the process working directory.
- `DataflowRuntime` now defaults writable runtime data to the application user-data root when no explicit `data_root` is supplied.
- Windows packaging now uses the full dependency profile as the official release build while still producing the neutral executable name `PyLabViewStudio.exe`.
- Windows version metadata, application version, README, and architecture documentation were updated for release 7.8.3.
- Core self-test no longer hardcodes release version `4.3.4`, allowing future application version changes without causing a false runtime self-test failure.

### Fixed

- Prevented stale runtime repaint from re-asserting the Capture Reference control after a momentary capture.
- Preserved spinning-drop measurement/table values after STOP while ensuring a new START begins a fresh measurement run.
- Improved mode-aware motor-stop handling so stale motor values do not restore an already stopped state in either Standard or Manual Mode.
- Kept stage/reference captures and measurement exports outside bundled application resources so frozen Windows builds can write safely under the user's Documents directory.

### Packaging

- `PyLabViewStudioFull.spec` is the full-profile PyInstaller build specification and includes application assets, examples, documentation, optional instrumentation dependencies, and the Manual spinning-drop handler.
- `build_windows_full.bat` builds the official Windows executable as `dist\PyLabViewStudio.exe`.
- GitHub Actions now uses one Windows build job for the full release profile.
- Tagged releases publish only:
  - `PyLabViewStudio.exe`
  - `PyLabViewStudio.exe.sha256`
- NI-DAQmx and the selected VISA backend still require their external vendor runtime/driver where applicable.

### Compatibility

- Project schema remains version 3.
- Existing schema-v3 projects remain compatible.
- V1/v2 project migration to schema v3 remains unchanged.
- The new Manual Mode behavior is represented through new node types, handlers, properties, and project wiring rather than a project-schema version change.

## [4.3.4] - 2026-08-26

### Fixed

- Properties Apply now synchronizes the Front Panel's cached control value so a value edited in the inspector (for example switching the Camera Mode constant from `usb` to `network`) reaches Run Once even before a Save. Previously the panel held a stale override and execution silently used the old value. Operate-mode control edits are still preserved on ordinary redraws.

- The spinning-drop example no longer produces an identical "Picture Oil" and "Picture Comparison". The two captures now run as distinct trigger domains: the oil camera captures live each tick, while the wire-comparison camera holds its last frame and only re-captures when the operator presses the new "Capture Reference" button.

- `examples/spinning_drop_ift.json` defaults Camera Mode to `network`, matching the DroidCam setup, and adds the staged wire-capture button.

### Compatibility

- Project schema remains version 3. `camera_capture_dual_mode` gained a `capture_trigger` boolean input; existing captured images and node wiring remain compatible because an unwired trigger defaults to live behavior.

## [4.3.3] - 2026-08-26

### Added

- Plain mouse-wheel vertical scrolling for both Front Panel and Block Diagram canvases, with native wheel handling on Windows/macOS and Button-4/Button-5 handling on Linux/X11.

### Compatibility

- `Ctrl + mouse wheel` remains zoom and `Shift + mouse wheel` remains horizontal scrolling. No project data or schema behavior changed.

## [4.3.2] - 2026-08-26

### Added

- `Ctrl + mouse wheel` zoom for both the Front Panel and Block Diagram canvases, bounded to 55%–200% and anchored at the pointer position.

- `Shift + mouse wheel` horizontal scrolling for both canvases, including Windows/macOS-style wheel events and Linux/X11 button events.

### Fixed

- Block Diagram hit testing and node dragging now use scroll-aware canvas coordinates, so editing remains accurate after viewport movement.

- Front Panel hit testing, control operation, dragging, and resizing now convert viewport coordinates back to document coordinates at every zoom level.

- Front Panel fonts and image fitting now follow the viewport zoom instead of overflowing their scaled widget bounds.

- Large Block Diagrams now expose a graph-sized scroll region rather than clipping content to the visible widget dimensions.

### Compatibility

- Project schema remains version 3. Zoom and scroll position are UI-only state and do not modify or dirty persisted node or Front Panel coordinates.

[7.9.0]: https://github.com/yuwanch3/py-labView/releases/tag/v7.9.0
[7.8.3]: https://github.com/yuwanch3/py-labView/releases/tag/v7.8.3
[4.3.4]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.4
[4.3.3]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.3
[4.3.2]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.2
