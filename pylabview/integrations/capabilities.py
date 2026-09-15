from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module, metadata
from multiprocessing import get_context
from multiprocessing.connection import Connection
from shutil import which
from typing import Any, Callable


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    version: str = ""
    reason: str = ""
    details: tuple[str, ...] = ()


@dataclass
class IntegrationDiagnostics:
    adapters: list[Capability] = field(default_factory=list)
    ni_devices: list[str] = field(default_factory=list)
    visa_resources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    realtime: Capability = field(default_factory=lambda: Capability(
        "Real-time target", False, reason="desktop CPython runtime is non-real-time; no target responded"))


def module_capability(display_name: str, module_name: str, distribution: str | None = None) -> Capability:
    try:
        module = import_module(module_name)
    except Exception as exc:
        return Capability(display_name, False, reason=f"{module_name} is not installed: {exc}")
    version = getattr(module, "__version__", "")
    if not version:
        try:
            version = metadata.version(distribution or module_name.split(".")[0])
        except Exception:
            version = "unknown"
    return Capability(display_name, True, str(version))


def collect_diagnostics(*, refresh_hardware: bool = False,
                        module_loader: Callable[[str], Any] = import_module,
                        nidaq_backend: Any = None, visa_resource_manager: Callable[..., Any] | None = None,
                        command_finder: Callable[[str], str | None] = which,
                        target_manifest: dict[str, Any] | None = None,
                        target_probe: Callable[[dict[str, Any] | None], Any] | None = None) -> IntegrationDiagnostics:
    """Collect headless diagnostics. Hardware enumeration only occurs on refresh."""
    result = IntegrationDiagnostics()
    modules = (("NI-DAQmx", "nidaqmx", "nidaqmx"), ("VISA", "pyvisa", "PyVISA"),
               ("Serial", "serial", "pyserial"), ("OPC UA", "asyncua", "asyncua"),
               ("OpenCV", "cv2", "opencv-python"), ("NumPy", "numpy", "numpy"),
               ("XLSX", "openpyxl", "openpyxl"), ("DOCX", "docx", "python-docx"),
               ("PDF", "reportlab", "reportlab"))
    loaded: dict[str, Any] = {}
    for display, module_name, distribution in modules:
        try:
            module = module_loader(module_name)
            loaded[module_name] = module
            version = getattr(module, "__version__", "")
            if not version:
                try: version = metadata.version(distribution)
                except Exception: version = "unknown"
            result.adapters.append(Capability(display, True, str(version)))
        except Exception as exc:
            result.adapters.append(Capability(display, False, reason=f"{module_name} unavailable: {exc}"))
    result.adapters.insert(0, Capability("HTML/CSV reports", True, "stdlib"))
    for tool in ("yosys", "vivado", "quartus_sh"):
        path = command_finder(tool)
        result.adapters.append(Capability(f"FPGA tool: {tool}", bool(path), details=(path,) if path else (),
                                                  reason="command not found" if not path else ""))
    if refresh_hardware:
        try:
            backend = nidaq_backend or loaded.get("nidaqmx")
            if backend is not None:
                result.ni_devices = [str(getattr(device, "name", device))
                                     for device in backend.system.System.local().devices]
        except Exception as exc:
            result.errors.append(f"NI device discovery failed: {exc}")
        try:
            factory = visa_resource_manager
            if factory is None and loaded.get("pyvisa") is not None:
                factory = loaded["pyvisa"].ResourceManager
            if factory:
                manager = factory()
                try: result.visa_resources = [str(item) for item in manager.list_resources()]
                finally: manager.close()
        except Exception as exc:
            result.errors.append(f"VISA resource discovery failed: {exc}")
        if target_manifest:
            try:
                if target_probe is None:
                    from ..targets import probe_target
                    target_probe = probe_target
                status = target_probe(target_manifest)
                result.realtime = Capability("Real-time target", bool(status.available),
                                             reason=str(status.reason), details=tuple(status.capabilities))
            except Exception as exc:
                result.errors.append(f"Runtime target handshake failed: {exc}")
    return result


def _diagnostics_worker(connection: Connection, target_manifest: dict[str, Any] | None) -> None:
    try:
        connection.send(collect_diagnostics(refresh_hardware=True, target_manifest=target_manifest))
    except BaseException as exc:
        connection.send(IntegrationDiagnostics(errors=[f"Hardware diagnostics failed: {type(exc).__name__}: {exc}"]))
    finally:
        connection.close()


def collect_hardware_diagnostics_bounded(*, timeout: float = 10,
                                         target_manifest: dict[str, Any] | None = None,
                                         _worker: Callable[[Connection, dict[str, Any] | None], None] = _diagnostics_worker
                                         ) -> IntegrationDiagnostics:
    """Run vendor enumeration in a disposable process with a wall-clock bound."""
    timeout = float(timeout)
    if timeout <= 0 or timeout > 60: raise ValueError("diagnostics timeout must be greater than 0 and at most 60 seconds")
    context = get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, target_manifest), daemon=True)
    try:
        process.start(); child.close()
        if not parent.poll(timeout):
            process.terminate(); process.join(1)
            return IntegrationDiagnostics(errors=[f"Hardware diagnostics timed out after {timeout:g} seconds"])
        try:
            result = parent.recv()
        except EOFError:
            return IntegrationDiagnostics(errors=["Hardware diagnostics process exited without a result"])
        if not isinstance(result, IntegrationDiagnostics):
            return IntegrationDiagnostics(errors=["Hardware diagnostics returned an invalid result"])
        process.join(1)
        return result
    finally:
        parent.close()
        try: child.close()
        except OSError: pass
        if process.is_alive(): process.terminate(); process.join(1)


def diagnostics_text(diagnostics: IntegrationDiagnostics) -> str:
    lines = [f"{item.name}: {'available' if item.available else 'unavailable'}"
             + (f" ({item.version})" if item.version else "")
             + (f" - {item.reason}" if item.reason else "") for item in diagnostics.adapters]
    lines += ["NI devices: " + (", ".join(diagnostics.ni_devices) or "none reported")]
    lines += ["VISA resources: " + (", ".join(diagnostics.visa_resources) or "none reported")]
    lines += [f"Real-time target: {'available' if diagnostics.realtime.available else 'unavailable'}"
              + (f" - {diagnostics.realtime.reason}" if diagnostics.realtime.reason else "")]
    lines += diagnostics.errors
    return "\n".join(lines)
