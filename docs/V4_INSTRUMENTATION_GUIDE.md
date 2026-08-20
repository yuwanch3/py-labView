# V4 Instrumentation Guide

## Setup

Install only required packages from `requirements-optional.txt`. The diagnostics dialog reports package version and an explicit reason when unavailable. **Refresh Hardware** is the only UI action that enumerates NI devices or VISA resources.

NI-DAQmx requires the official Python package plus the NI-DAQmx runtime/driver from NI. Configure DAQ node `driver=nidaqmx` and a vendor physical channel such as `Dev1/ai0`; finite AI uses `samples`, `rate`, and `timeout`. Device ranges/rates still must match the specific hardware.

PyVISA requires a ResourceManager backend. Install a vendor VISA runtime or an appropriate backend such as `pyvisa-py`, then use the resource string reported by diagnostics. VISA writes are bounded before dispatch; response `max_bytes` is post-read validation because portable PyVISA APIs return the complete message. It does not cap backend allocation. Operations on one instrument are serialized.

PySerial accepts normal ports and backend-supported URLs. Read/write mode is `bytes` or `text`; text uses the configured encoding. OPC UA accepts `opc.tcp://` or `https://`; configure certificates and security policy according to deployment requirements. V4 implements value read/write only, not subscriptions. Stop requests are cooperative: calls that a vendor library cannot interrupt finish no later than their configured timeout, then worker-owned cleanup closes the handle.

Vision wires use the transient `image` type and validate `ImageFrame` shape, dtype, and decoded byte metadata. File size is checked before `cv2.imread`, but compressed-image decode may allocate memory before decoded dimensions are known. Treat untrusted image decode as requiring a separately resource-limited process.

Vision file paths and report destinations are relative to runtime `data_root`. Camera Capture opens one index, obtains one frame, and releases it. The `ImageFrame.payload` is intentionally not persisted. HTML/CSV need no optional package; XLSX uses `openpyxl`, DOCX uses `python-docx`, PDF uses `reportlab`.

## FPGA And RT Boundaries

**Export Verilog** accepts only inputs/constants, add/subtract/multiply, compare, and/or/not, select, and outputs. It rejects loops, files, network, plugins, and dynamic behavior. Optional Yosys support performs a syntax read with a subprocess timeout. This is an HDL export subset, not an FPGA compilation module, and does not generate a bitstream.

The integrated runtime is desktop CPython and non-real-time. `targets.py` only defines a bounded manifest/handshake for an actual external runtime. Diagnostics remains unavailable unless a configured target responds; even a response is not proof of hard-real-time behavior.
