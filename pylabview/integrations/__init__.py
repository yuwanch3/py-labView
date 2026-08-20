"""Optional instrumentation adapters.

Importing this package never requires third-party modules. Adapters load their
backend lazily and expose an explicit capability when it is absent.
"""

from .capabilities import Capability, IntegrationDiagnostics, collect_diagnostics, collect_hardware_diagnostics_bounded
from .nidaqmx_adapter import NIDAQmxDriver
from .opcua_adapter import OpcUaAdapter
from .reports_adapter import ReportsAdapter
from .serial_adapter import SerialAdapter
from .visa_adapter import VisaAdapter
from .vision_adapter import ImageFrame, VisionAdapter

__all__ = [
    "Capability", "ImageFrame", "IntegrationDiagnostics", "NIDAQmxDriver",
    "OpcUaAdapter", "ReportsAdapter", "SerialAdapter", "VisaAdapter", "VisionAdapter",
    "collect_diagnostics", "collect_hardware_diagnostics_bounded",
]
