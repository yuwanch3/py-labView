# Hardware Validation Status

| Subsystem | Implemented | Automated evidence | Physical validation |
|---|---|---|---|
| Simulated DAQ | Yes | Unit tests | Not applicable |
| NI-DAQmx AI/AO/DI/DO | Yes | Injected fake API, sequence/bounds/cleanup | **Not performed** |
| VISA | Yes | Fake ResourceManager/instrument | **Not performed** |
| Serial | Yes | Fake stream; pyserial loop URL optional | **Not performed** |
| OPC UA value read/write | Yes | Fake sync client | No physical/production server qualification |
| Modbus TCP FC01/02/03/04/05/06/15/16 | Yes | Local stub/vector tests | No vendor device qualification |
| OpenCV vision operators | Yes | Fake unit tests; actual in-memory OpenCV/NumPy only in full frozen self-test, no camera | No industrial camera/vision validation |
| HTML/CSV reports | Yes | Actual temporary files | Not applicable |
| XLSX/DOCX/PDF reports | Yes when package installed | Fake unit tests plus dependency import in full frozen self-test | No compliance certification |
| Verilog subset | Yes | Golden/rejection tests | No board, synthesis timing, or bitstream validation |
| External RT target | Handshake contract only | Fake socket | No qualified target |

PyLabView Studio 4.0.0 is not safety-rated, medically certified, hard real-time, or qualified for control of hazardous processes. Users must perform device-specific installation, calibration, electrical protection, fault handling, cybersecurity, and acceptance testing.
