# Changelog

All notable user-facing changes to PyLabView Studio are recorded here.

## [4.3.4] - 2026-08-26

### Fixed

- Properties Apply now synchronizes the Front Panel's cached control value so a value edited in the inspector (for example switching the Camera Mode constant from `usb` to `network`) reaches Run Once even before a Save. Previously the panel held a stale override and execution silently used the old value. Operate-mode control edits are still preserved on ordinary redraws.
- The spinning-drop example no longer produces an identical "Picture Oil" and "Picture Comparison". The two captures now run as distinct trigger domains: the oil camera captures live each tick, while the wire-comparison camera holds its last frame and only re-captures when the operator presses the new "Capture Reference" button.
- `examples/spinning_drop_ift.json` defaults Camera Mode to `network`, matching the DroidCam setup, and adds the staged wire-capture button.

### Compatibility

- Project schema remains version 3. `camera_capture_dual_mode` gained a `capture_trigger` boolean input; existing captured images and node wiring remain compatible because an unwired trigger defaults to live behavior.

[4.3.4]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.4
[4.3.3]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.3

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

[4.3.3]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.3
[4.3.2]: https://github.com/yuwanch3/py-labView/releases/tag/v4.3.2
