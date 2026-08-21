from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from threading import Lock
import math


MAX_IMAGE_PIXELS = 100_000_000
MAX_IMAGE_FILE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_MEMORY_BYTES = 512 * 1024 * 1024
MAX_PROFILE_PIXELS = 4_000_000
SUPPORTED_IMAGE_DTYPES = {"uint8", "uint16", "float32", "float64"}


@dataclass(frozen=True)
class ImageFrame:
    """Non-persistable in-memory image payload with bounded metadata."""
    payload: Any
    width: int
    height: int
    channels: int

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.width * self.height > MAX_IMAGE_PIXELS:
            raise ValueError("image dimensions are outside bounds")
        if self.channels not in (1, 3, 4): raise ValueError("image channels must be 1, 3, or 4")
        shape = getattr(self.payload, "shape", ())
        expected = (self.height, self.width) if self.channels == 1 else (self.height, self.width, self.channels)
        if tuple(shape) != expected: raise ValueError("image metadata does not match payload shape")
        dtype = getattr(self.payload, "dtype", None)
        dtype_name, itemsize = str(getattr(dtype, "name", dtype)), getattr(dtype, "itemsize", None)
        if dtype_name not in SUPPORTED_IMAGE_DTYPES or not isinstance(itemsize, int) or itemsize < 1:
            raise ValueError("image payload dtype is unsupported")
        minimum_bytes = self.width * self.height * self.channels * itemsize
        nbytes = getattr(self.payload, "nbytes", None)
        if not isinstance(nbytes, int) or nbytes < minimum_bytes or nbytes > MAX_IMAGE_MEMORY_BYTES:
            raise ValueError("image payload memory size is invalid")


class VisionAdapter:
    def __init__(self, cv2_backend: Any = None, numpy_backend: Any = None) -> None:
        self.cv2, self.numpy = cv2_backend, numpy_backend
        self._capture_lock = Lock()

    @property
    def available(self) -> bool:
        try: self._backends(); return True
        except RuntimeError: return False

    def _backends(self) -> tuple[Any, Any]:
        try:
            return self.cv2 or import_module("cv2"), self.numpy or import_module("numpy")
        except Exception as exc: raise RuntimeError(f"OpenCV/NumPy unavailable: {exc}") from exc

    @staticmethod
    def _frame(payload: Any) -> ImageFrame:
        shape = getattr(payload, "shape", ())
        if len(shape) not in (2, 3): raise ValueError("OpenCV returned an invalid image")
        height, width = int(shape[0]), int(shape[1]); channels = 1 if len(shape) == 2 else int(shape[2])
        return ImageFrame(payload, width, height, channels)

    @staticmethod
    def _require_frame(frame: Any) -> ImageFrame:
        if not isinstance(frame, ImageFrame): raise TypeError("vision operation requires an ImageFrame")
        return frame

    def read(self, path: Path) -> ImageFrame:
        size = path.stat().st_size
        if size < 1 or size > MAX_IMAGE_FILE_BYTES: raise ValueError("image file size is outside bounds")
        cv2, _ = self._backends(); payload = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if payload is None: raise OSError(f"unable to read image: {path.name}")
        return self._frame(payload)

    def capture(self, camera_index: int | str = 0, timeout: float = 5.0) -> ImageFrame:
        cv2, _ = self._backends()
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
            raise ValueError("camera timeout must be greater than 0 and at most 300 seconds")
        if isinstance(camera_index, str):
            source = camera_index.strip()
            parsed = urlsplit(source)
            if len(source) > 2048 or parsed.scheme not in ("http", "https", "rtsp") or not parsed.netloc:
                raise ValueError("network camera URL must use http, https, or rtsp")
        else:
            source = int(camera_index)
            if not 0 <= source <= 64: raise ValueError("camera index must be between 0 and 64")
        with self._capture_lock:
            timeout_ms = max(1, int(timeout * 1000))
            parameters = []
            for name in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
                if hasattr(cv2, name):
                    parameters.extend((getattr(cv2, name), timeout_ms))
            try:
                capture = (cv2.VideoCapture(source, getattr(cv2, "CAP_ANY", 0), parameters)
                           if parameters else cv2.VideoCapture(source))
            except TypeError:
                capture = cv2.VideoCapture(source)
            try:
                if not capture.isOpened(): raise OSError("camera could not be opened")
                ok, payload = capture.read()
                if not ok or payload is None: raise OSError("camera did not return a frame")
                return self._frame(payload)
            finally: capture.release()

    def capture_source(self, mode: str, device_index: Any, network_url: Any, timeout: float = 5.0) -> ImageFrame:
        mode = str(mode).strip().lower()
        if mode == "usb":
            if isinstance(device_index, bool) or isinstance(device_index, float) and not device_index.is_integer():
                raise ValueError("USB camera source must be an integer device index")
            return self.capture(int(device_index), timeout)
        if mode == "network":
            if not isinstance(network_url, str):
                raise ValueError("network camera source must be a URL string")
            return self.capture(network_url, timeout)
        raise ValueError("camera mode must be 'usb' or 'network'")

    def grayscale(self, frame: ImageFrame) -> ImageFrame:
        frame = self._require_frame(frame)
        if frame.channels == 1: return frame
        cv2, _ = self._backends(); return self._frame(cv2.cvtColor(frame.payload, cv2.COLOR_BGR2GRAY))

    def blur(self, frame: ImageFrame, kernel: int) -> ImageFrame:
        frame = self._require_frame(frame)
        kernel = int(kernel)
        if kernel < 1 or kernel > 99 or kernel % 2 == 0: raise ValueError("Gaussian kernel must be odd and between 1 and 99")
        cv2, _ = self._backends(); return self._frame(cv2.GaussianBlur(frame.payload, (kernel, kernel), 0))

    def threshold(self, frame: ImageFrame, threshold: float, maximum: float = 255) -> ImageFrame:
        frame = self._require_frame(frame)
        cv2, _ = self._backends(); source = self.grayscale(frame)
        _, payload = cv2.threshold(source.payload, float(threshold), float(maximum), cv2.THRESH_BINARY)
        return self._frame(payload)

    def edge_intensity_profile(self, frame: ImageFrame, orientation: str, threshold: float = 127,
                               foreground: str = "dark") -> dict[str, Any]:
        source = self.grayscale(self._require_frame(frame))
        if source.width * source.height > MAX_PROFILE_PIXELS:
            raise ValueError("edge profile image exceeds the 4 million pixel processing bound")
        orientation = str(orientation).strip().lower()
        if orientation not in ("horizontal", "vertical"):
            raise ValueError("scan orientation must be 'horizontal' or 'vertical'")
        threshold = float(threshold)
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("edge threshold must be finite and non-negative")
        foreground = str(foreground).strip().lower()
        if foreground not in ("dark", "light"):
            raise ValueError("edge foreground must be 'dark' or 'light'")
        try:
            scanline = (source.payload[source.height // 2] if orientation == "horizontal"
                        else source.payload[:, source.width // 2])
            profile = [float(value) for value in scanline.tolist()]
        except (IndexError, TypeError):
            rows = source.payload.tolist()
            if not isinstance(rows, list) or len(rows) != source.height or any(
                    not isinstance(row, list) or len(row) != source.width for row in rows):
                raise ValueError("image payload cannot be converted to a pixel matrix")
            profile = ([float(value) for value in rows[source.height // 2]] if orientation == "horizontal"
                       else [float(row[source.width // 2]) for row in rows])
        active = [(value <= threshold) if foreground == "dark" else (value >= threshold) for value in profile]
        longest = current = 0
        for enabled in active:
            current = current + 1 if enabled else 0
            longest = max(longest, current)
        if longest == 0:
            raise ValueError("no foreground region crosses the configured threshold")
        return {"intensity_profile": profile, "edge_image": self.threshold(source, threshold, 255),
                "diameter_px": float(longest)}

    def canny(self, frame: ImageFrame, low: float, high: float) -> ImageFrame:
        frame = self._require_frame(frame)
        if not 0 <= float(low) <= float(high): raise ValueError("Canny thresholds must satisfy 0 <= low <= high")
        cv2, _ = self._backends(); return self._frame(cv2.Canny(self.grayscale(frame).payload, low, high))

    def resize(self, frame: ImageFrame, width: int, height: int) -> ImageFrame:
        frame = self._require_frame(frame)
        width, height = int(width), int(height)
        if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS: raise ValueError("resize dimensions are outside bounds")
        cv2, _ = self._backends(); return self._frame(cv2.resize(frame.payload, (width, height)))

    def template_match(self, frame: ImageFrame, template: ImageFrame) -> dict[str, Any]:
        frame, template = self._require_frame(frame), self._require_frame(template)
        if frame.channels != template.channels: raise ValueError("template and source channels must match")
        if template.width > frame.width or template.height > frame.height: raise ValueError("template is larger than source image")
        cv2, _ = self._backends(); result = cv2.matchTemplate(frame.payload, template.payload, cv2.TM_CCOEFF_NORMED)
        _minimum, score, _minimum_location, location = cv2.minMaxLoc(result)
        return {"score": float(score), "x": int(location[0]), "y": int(location[1])}

    def save(self, frame: ImageFrame, path: Path) -> None:
        frame = self._require_frame(frame)
        cv2, _ = self._backends()
        if not cv2.imwrite(str(path), frame.payload): raise OSError(f"unable to save image: {path.name}")
