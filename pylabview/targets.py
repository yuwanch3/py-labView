from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import json
import socket


@dataclass(frozen=True)
class TargetStatus:
    available: bool
    name: str = ""
    capabilities: tuple[str, ...] = ()
    reason: str = "desktop CPython runtime is non-real-time; no external target configured"


def probe_target(manifest: dict[str, Any] | None, connector: Callable[..., socket.socket] = socket.create_connection) -> TargetStatus:
    """Perform an optional bounded JSON-line handshake; this does not imply hard RT."""
    if not manifest: return TargetStatus(False)
    if set(manifest) != {"host", "port", "timeout"}: raise ValueError("invalid target manifest")
    timeout = float(manifest["timeout"])
    if timeout <= 0 or timeout > 10: raise ValueError("target timeout must be greater than 0 and at most 10 seconds")
    sock = connector((str(manifest["host"]), int(manifest["port"])), timeout=timeout)
    try:
        sock.settimeout(timeout); sock.sendall(b'{"protocol":"pylabview-target","version":1}\n')
        response = sock.recv(8193)
        if len(response) > 8192 or not response.endswith(b"\n"): raise ValueError("invalid target handshake size/framing")
        data = json.loads(response)
        if not isinstance(data, dict) or data.get("protocol") != "pylabview-target" or data.get("version") != 1 or data.get("status") != "ready":
            raise ValueError("target handshake rejected")
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities): raise ValueError("invalid target capabilities")
        return TargetStatus(True, str(data.get("name", "external target")), tuple(capabilities), "external target responded; hard RT is not asserted")
    finally: sock.close()
