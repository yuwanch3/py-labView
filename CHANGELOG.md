# Changelog

All notable user-facing changes to PyLabView Studio are recorded here.

## [8.0.0] - 2026-09-11

### Added

- Added session-based measurement storage under `Documents\GMJ PyLabView\Sessions`.
- Added one session folder per application launch and selected operating mode, including `Session_Info.json`.
- Added dedicated per-session capture folders for `Reference`, RPM-based `Stages`, and RPM-based `Analysis`.
- Added automatic 10-image stage capture batches for completed RPM measurements.
- Added synchronized Analysis PNG snapshots for every captured stage sample, containing Grafik Oil, Grafik Kawat, w², r³, IFT N/m, and IFT mN/m.
- Added a background Analysis rendering worker so PNG generation does not block normal Front Panel refresh.
- Added per-sample Picture Comparison and Grafik Kawat display updates during the 10-sample capture burst.
- Added three-sheet spinning-drop Excel workbooks containing Measurement Summary, Stage Samples, and Statistics.

### Changed

- Measurement results now use the active session as the primary storage root.
- Excel measurement exports are written to each session's `Measurements` directory.
- Automatic stage captures are stored under `Sessions\...\Captures\Stages\<RPM>_RPM`.
- Analysis snapshots are stored separately under `Sessions\...\Captures\Analysis\<RPM>_RPM`.
- Picture Comparison can visibly follow each stage sample while the internal calibration reference remains frozen.
- Wire/reference scale calibration remains based on the operator's latest Capture Reference and is not replaced by automatic stage samples.
- Default Standard and Manual example projects are refreshed from the bundled application examples so first-run user copies track the release templates.
- Writable user-data startup structure was simplified to `Examples`, `Projects`, and `Sessions`.
- Application, Windows file metadata, README, and architecture documentation were updated for release 8.0.0.

### Fixed

- Prevented automatic stage samples from changing the frozen wire calibration / scale factor during a measurement run.
- Restored visible Picture Comparison and Grafik Kawat updates for all 10 stage samples.
- Prevented Analysis PNG rendering from blocking the Tkinter UI refresh path.
- Fixed Win64 GDI handle typing in the off-screen Analysis renderer.
- Fixed missing `Path` import used by Analysis PNG output.
- Kept Analysis snapshot data paired with the corresponding sample before background rendering.

### Cleanup

- Removed creation of the legacy top-level `Captures` directory.
- Removed creation and fallback use of the legacy top-level `Measurement Exports` directory.
- Removed the legacy spinning-drop CSV report node and `spinning-drop-ift.csv` output from the bundled Standard and Manual projects.
- Kept session-based JPG, PNG, and XLSX outputs as the active spinning-drop measurement artifacts.

### Validation

- Manual RPM Mode source operation was re-tested successfully at 1500 RPM with session creation, 10 raw stage JPG captures, 10 Analysis PNG captures, measurement data, and Excel output.
- Fresh user-data generation was verified after deleting `Documents\GMJ PyLabView`.
- Standard Mode and Manual RPM Mode remain separate operating workflows.
- Project schema remains version 3.
- Existing schema-v3 projects remain compatible.
- V1/v2 migration behavior remains unchanged.
- Full automated regression testing for the 8.0.0 release should be completed before tagging the release.

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
- Added automatic copying of the default Standard and Manual example projects into `Documents\GMJ PyLabView\Examples` when they are missing.
- Added centralized application path handling for bundled resources and writable user data.
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

- Properties Apply now synchronizes the Front Panel's cached control value so a value edited in the inspector reaches Run Once even before a Save.
- The spinning-drop example no longer produces an identical Picture Oil and Picture Comparison.
- `examples/spinning_drop_ift.json` defaults Camera Mode to `network` and adds the staged wire-capture button.

### Compatibility

- Project schema remains version 3.

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

- Block Diagram hit testing and node dragging now use scroll-aware canvas coordinates.
- Front Panel hit testing, control operation, dragging, and resizing now convert viewport coordinates back to document coordinates at every zoom level.
- Front Panel fonts and image fitting now follow viewport zoom.
- Large Block Diagrams expose a graph-sized scroll region.

### Compatibility

- Project schema remains version 3.

[8.0.0]: https://github.com/yuwanch3/py-labView/releases/tag/v8.0.0
[7.9.0]: https://github.com/yuwanch3/py-labView/releases/tag/v7.9.0
[7.8.3]: https://github.com/yuwanch3/py-labView/releases/tag/v7.8.3
[4.3.4]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.4
[4.3.3]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.3
[4.3.2]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.2
