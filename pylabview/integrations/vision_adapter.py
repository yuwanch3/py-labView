from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from threading import Event, Lock, Thread
from statistics import median
import math
import time


MAX_IMAGE_PIXELS = 100_000_000
MAX_IMAGE_FILE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_MEMORY_BYTES = 512 * 1024 * 1024
MAX_PROFILE_PIXELS = 4_000_000

SUPPORTED_IMAGE_DTYPES = {
    "uint8",
    "uint16",
    "float32",
    "float64",
}


@dataclass(frozen=True)
class ImageFrame:
    """Non-persistable in-memory image payload with bounded metadata."""

    payload: Any
    width: int
    height: int
    channels: int
    captured_at: float | None = None
    frame_sequence: int | None = None

    def __post_init__(self) -> None:

        if (
            self.width < 1
            or self.height < 1
            or self.width * self.height > MAX_IMAGE_PIXELS
        ):
            raise ValueError(
                "image dimensions are outside bounds"
            )

        if self.channels not in (1, 3, 4):
            raise ValueError(
                "image channels must be 1, 3, or 4"
            )

        shape = getattr(
            self.payload,
            "shape",
            (),
        )

        expected = (
            (self.height, self.width)
            if self.channels == 1
            else (
                self.height,
                self.width,
                self.channels,
            )
        )

        if tuple(shape) != expected:
            raise ValueError(
                "image metadata does not match payload shape"
            )

        dtype = getattr(
            self.payload,
            "dtype",
            None,
        )

        dtype_name = str(
            getattr(
                dtype,
                "name",
                dtype,
            )
        )

        itemsize = getattr(
            dtype,
            "itemsize",
            None,
        )

        if (
            dtype_name not in SUPPORTED_IMAGE_DTYPES
            or not isinstance(itemsize, int)
            or itemsize < 1
        ):
            raise ValueError(
                "image payload dtype is unsupported"
            )

        minimum_bytes = (
            self.width
            * self.height
            * self.channels
            * itemsize
        )

        nbytes = getattr(
            self.payload,
            "nbytes",
            None,
        )

        if (
            not isinstance(nbytes, int)
            or nbytes < minimum_bytes
            or nbytes > MAX_IMAGE_MEMORY_BYTES
        ):
            raise ValueError(
                "image payload memory size is invalid"
            )


class _CameraWorker:
    """
    Background camera reader.

    Kamera dibuka satu kali.
    Frame dibaca terus di background thread.
    Hanya frame terbaru yang disimpan.
    """

    def __init__(
        self,
        cv2: Any,
        source: Any,
    ) -> None:

        self.cv2 = cv2
        self.source = source

        # Network streams (DroidCam/HTTP/RTSP) use a freshness-first
        # strategy. USB cameras keep the original read() behaviour.
        self.is_network_source = isinstance(
            source,
            str,
        )
        self.network_grab_count = 3

        self.capture: Any = None

        self.frame_lock = Lock()

        self.latest_frame: Any = None
        self.latest_frame_captured_at: float | None = None
        self.latest_frame_sequence: int | None = None
        self._frame_sequence = 0
        self.last_error: Exception | None = None

        self.stop_event = Event()
        self.frame_ready = Event()

        self.thread: Thread | None = None

        self.started = False

    def start(self) -> None:

        if self.started:
            return

        self.started = True

        self.thread = Thread(
            target=self._run,
            name=f"PyLabViewCamera-{self.source}",
            daemon=True,
        )

        self.thread.start()

    def _open_capture(self) -> Any:

        capture = self.cv2.VideoCapture(
            self.source
        )

        if not capture.isOpened():

            try:
                capture.release()
            except Exception:
                pass

            raise OSError(
                "camera could not be opened"
            )

        # Kurangi buffering kamera kalau backend mendukung.
        if hasattr(
            self.cv2,
            "CAP_PROP_BUFFERSIZE",
        ):

            try:
                capture.set(
                    self.cv2.CAP_PROP_BUFFERSIZE,
                    1,
                )
            except Exception:
                pass

        return capture

    def _run(self) -> None:

        try:

            self.capture = (
                self._open_capture()
            )

            while not self.stop_event.is_set():

                # Network camera / DroidCam:
                # discard a few queued frames, then retrieve the
                # freshest available frame.
                #
                # USB cameras retain the original capture.read().
                if (
                    self.is_network_source
                    and hasattr(
                        self.capture,
                        "grab",
                    )
                    and hasattr(
                        self.capture,
                        "retrieve",
                    )
                ):

                    ok = True

                    for _ in range(
                        self.network_grab_count
                    ):

                        if self.stop_event.is_set():
                            ok = False
                            break

                        ok = self.capture.grab()

                        if not ok:
                            break

                    if ok:

                        ok, payload = (
                            self.capture.retrieve()
                        )

                    else:

                        payload = None

                else:

                    # USB cameras and lightweight/mock capture
                    # backends keep the original read() path.
                    ok, payload = (
                        self.capture.read()
                    )

                if (
                    not ok
                    or payload is None
                ):

                    self.last_error = OSError(
                        "camera did not return a frame"
                    )

                    time.sleep(
                        0.05
                    )

                    continue

                with self.frame_lock:

                    # Hanya simpan frame terbaru.
                    # Frame lama otomatis dibuang.
                    self.latest_frame = (
                        payload.copy()
                    )

                    # Diagnostic metadata only.
                    self._frame_sequence += 1
                    self.latest_frame_sequence = self._frame_sequence
                    self.latest_frame_captured_at = time.monotonic()

                    self.last_error = None

                self.frame_ready.set()

        except Exception as exc:

            self.last_error = exc

            self.frame_ready.set()

        finally:

            if self.capture is not None:

                try:
                    self.capture.release()
                except Exception:
                    pass

                self.capture = None

    def get_frame(
        self,
        timeout: float,
    ) -> tuple[Any, float | None, int | None]:

        if not self.frame_ready.wait(
            timeout
        ):
            raise OSError(
                "camera timed out waiting for first frame"
            )

        with self.frame_lock:

            if self.latest_frame is not None:

                return (
                    self.latest_frame.copy(),
                    self.latest_frame_captured_at,
                    self.latest_frame_sequence,
                )

        if self.last_error is not None:
            raise OSError(
                str(self.last_error)
            )

        raise OSError(
            "camera did not return a frame"
        )

    def stop(self) -> None:

        self.stop_event.set()

        # Prefer letting the worker leave grab/read/retrieve and
        # release VideoCapture from its own thread. Releasing a live
        # FFmpeg capture concurrently can trigger native assertions.
        if (
            self.thread is not None
            and self.thread.is_alive()
        ):

            try:
                self.thread.join(
                    timeout=1.0
                )
            except Exception:
                pass

        # Fallback only if the worker did not stop in time.
        if (
            self.thread is not None
            and self.thread.is_alive()
            and self.capture is not None
        ):

            try:
                self.capture.release()
            except Exception:
                pass

            try:
                self.thread.join(
                    timeout=1.0
                )
            except Exception:
                pass

        self.capture = None


class VisionAdapter:

    def __init__(
        self,
        cv2_backend: Any = None,
        numpy_backend: Any = None,
    ) -> None:

        self.cv2 = cv2_backend
        self.numpy = numpy_backend

        self._worker_lock = Lock()

        self._camera_workers: dict[
            tuple[str, Any],
            _CameraWorker
        ] = {}

    @property
    def available(self) -> bool:

        try:
            self._backends()
            return True

        except RuntimeError:
            return False

    def _backends(
        self,
    ) -> tuple[Any, Any]:

        try:

            return (
                self.cv2
                or import_module(
                    "cv2"
                ),
                self.numpy
                or import_module(
                    "numpy"
                ),
            )

        except Exception as exc:

            raise RuntimeError(
                f"OpenCV/NumPy unavailable: {exc}"
            ) from exc

    @staticmethod
    def _frame(
        payload: Any,
        captured_at: float | None = None,
        frame_sequence: int | None = None,
    ) -> ImageFrame:

        shape = getattr(
            payload,
            "shape",
            (),
        )

        if len(shape) not in (
            2,
            3,
        ):
            raise ValueError(
                "OpenCV returned an invalid image"
            )

        height = int(
            shape[0]
        )

        width = int(
            shape[1]
        )

        channels = (
            1
            if len(shape) == 2
            else int(
                shape[2]
            )
        )

        return ImageFrame(
            payload,
            width,
            height,
            channels,
            captured_at,
            frame_sequence,
        )

    @staticmethod
    def _require_frame(
        frame: Any,
    ) -> ImageFrame:

        if not isinstance(
            frame,
            ImageFrame,
        ):
            raise TypeError(
                "vision operation requires an ImageFrame"
            )

        return frame

    # ============================================================
    # IMAGE FILE
    # ============================================================

    def read(
        self,
        path: Path,
    ) -> ImageFrame:

        size = path.stat().st_size

        if (
            size < 1
            or size > MAX_IMAGE_FILE_BYTES
        ):
            raise ValueError(
                "image file size is outside bounds"
            )

        cv2, _ = (
            self._backends()
        )

        payload = cv2.imread(
            str(path),
            cv2.IMREAD_UNCHANGED,
        )

        if payload is None:
            raise OSError(
                f"unable to read image: {path.name}"
            )

        return self._frame(
            payload
        )

    # ============================================================
    # CAMERA WORKER
    # ============================================================

    def _get_or_create_worker(
        self,
        key: tuple[str, Any],
        source: Any,
    ) -> _CameraWorker:

        cv2, _ = (
            self._backends()
        )

        with self._worker_lock:

            worker = (
                self._camera_workers.get(
                    key
                )
            )

            if worker is not None:

                if (
                    worker.thread is not None
                    and worker.thread.is_alive()
                ):
                    return worker

                try:
                    worker.stop()
                except Exception:
                    pass

                self._camera_workers.pop(
                    key,
                    None,
                )

            worker = _CameraWorker(
                cv2=cv2,
                source=source,
            )

            self._camera_workers[
                key
            ] = worker

            worker.start()

            return worker

    def release_all_captures(
        self,
    ) -> None:

        with self._worker_lock:

            workers = list(
                self._camera_workers.values()
            )

            self._camera_workers.clear()

        for worker in workers:

            try:
                worker.stop()
            except Exception:
                pass

    # ============================================================
    # CAMERA CAPTURE
    # ============================================================

    def capture(
        self,
        camera_index: int | str = 0,
        timeout: float = 5.0,
    ) -> ImageFrame:

        timeout = float(
            timeout
        )

        if (
            not math.isfinite(
                timeout
            )
            or timeout <= 0
            or timeout > 300
        ):
            raise ValueError(
                "camera timeout must be greater than 0 "
                "and at most 300 seconds"
            )

        # ========================================================
        # NETWORK CAMERA / DROIDCAM
        # ========================================================

        if isinstance(
            camera_index,
            str,
        ):

            source = (
                camera_index.strip()
            )

            parsed = urlsplit(
                source
            )

            if (
                len(source) > 2048
                or parsed.scheme
                not in (
                    "http",
                    "https",
                    "rtsp",
                )
                or not parsed.netloc
            ):
                raise ValueError(
                    "network camera URL must use "
                    "http, https, or rtsp"
                )

            key = (
                "network",
                source,
            )

            worker = (
                self._get_or_create_worker(
                    key=key,
                    source=source,
                )
            )

            (
                payload,
                captured_at,
                frame_sequence,
            ) = worker.get_frame(
                timeout
            )

            return self._frame(
                payload,
                captured_at,
                frame_sequence,
            )

        # ========================================================
        # USB CAMERA
        # ========================================================

        source = int(
            camera_index
        )

        if not (
            0 <= source <= 64
        ):
            raise ValueError(
                "camera index must be between 0 and 64"
            )

        key = (
            "usb",
            source,
        )

        worker = (
            self._get_or_create_worker(
                key=key,
                source=source,
            )
        )

        (
            payload,
            captured_at,
            frame_sequence,
        ) = worker.get_frame(
            timeout
        )

        return self._frame(
            payload,
            captured_at,
            frame_sequence,
        )

    def capture_source(
        self,
        mode: str,
        device_index: Any,
        network_url: Any,
        timeout: float = 5.0,
    ) -> ImageFrame:

        mode = str(
            mode
        ).strip().lower()

        if mode == "usb":

            if (
                isinstance(
                    device_index,
                    bool,
                )
                or (
                    isinstance(
                        device_index,
                        float,
                    )
                    and not device_index.is_integer()
                )
            ):
                raise ValueError(
                    "USB camera source must be "
                    "an integer device index"
                )

            return self.capture(
                int(
                    device_index
                ),
                timeout,
            )

        if mode == "network":

            if not isinstance(
                network_url,
                str,
            ):
                raise ValueError(
                    "network camera source must "
                    "be a URL string"
                )

            return self.capture(
                network_url,
                timeout,
            )

        raise ValueError(
            "camera mode must be "
            "'usb' or 'network'"
        )

    # ============================================================
    # GRAYSCALE
    # ============================================================

    def grayscale(
        self,
        frame: ImageFrame,
    ) -> ImageFrame:

        frame = (
            self._require_frame(
                frame
            )
        )

        if frame.channels == 1:
            return frame

        cv2, _ = (
            self._backends()
        )

        return self._frame(
            cv2.cvtColor(
                frame.payload,
                cv2.COLOR_BGR2GRAY,
            )
        )

    # ============================================================
    # BLUR
    # ============================================================

    def blur(
        self,
        frame: ImageFrame,
        kernel: int,
    ) -> ImageFrame:

        frame = (
            self._require_frame(
                frame
            )
        )

        kernel = int(
            kernel
        )

        if (
            kernel < 1
            or kernel > 99
            or kernel % 2 == 0
        ):
            raise ValueError(
                "Gaussian kernel must be odd "
                "and between 1 and 99"
            )

        cv2, _ = (
            self._backends()
        )

        return self._frame(
            cv2.GaussianBlur(
                frame.payload,
                (
                    kernel,
                    kernel,
                ),
                0,
            )
        )

    # ============================================================
    # THRESHOLD
    # ============================================================

    def threshold(
        self,
        frame: ImageFrame,
        threshold: float,
        maximum: float = 255,
    ) -> ImageFrame:

        frame = (
            self._require_frame(
                frame
            )
        )

        cv2, _ = (
            self._backends()
        )

        source = (
            self.grayscale(
                frame
            )
        )

        _, payload = (
            cv2.threshold(
                source.payload,
                float(
                    threshold
                ),
                float(
                    maximum
                ),
                cv2.THRESH_BINARY,
            )
        )

        return self._frame(
            payload
        )

    # ============================================================
    # EDGE INTENSITY PROFILE
    #
    # UPDATED:
    # - central ROI
    # - Gaussian blur
    # - multiple scanlines
    # - reject regions touching ROI border
    # - median diameter
    # ============================================================

    def edge_intensity_profile(
        self,
        frame: ImageFrame,
        orientation: str,
        threshold: float = 127,
        foreground: str = "dark",
        detection_mode: str = "scanline",
        tracking_hint: dict[str, float] | None = None,
    ) -> dict[str, Any]:

        frame = self._require_frame(
            frame
        )

        cv2, np = (
            self._backends()
        )

        # --------------------------------------------------------
        # Grayscale
        # --------------------------------------------------------

        gray = self.grayscale(
            frame
        )

        if (
            gray.width
            * gray.height
            > MAX_PROFILE_PIXELS
        ):
            raise ValueError(
                "edge profile image exceeds "
                "the 4 million pixel processing bound"
            )

        # --------------------------------------------------------
        # Validate orientation
        # --------------------------------------------------------

        orientation = str(
            orientation
        ).strip().lower()

        if orientation not in (
            "horizontal",
            "vertical",
        ):
            raise ValueError(
                "scan orientation must be "
                "'horizontal' or 'vertical'"
            )

        # --------------------------------------------------------
        # Validate threshold
        # --------------------------------------------------------

        threshold = float(
            threshold
        )

        if (
            not math.isfinite(
                threshold
            )
            or threshold < 0
            or threshold > 255
        ):
            raise ValueError(
                "edge threshold must be "
                "between 0 and 255"
            )

        # --------------------------------------------------------
        # Validate foreground
        # --------------------------------------------------------

        foreground = str(
            foreground
        ).strip().lower()

        if foreground not in (
            "dark",
            "light",
        ):
            raise ValueError(
                "edge foreground must be "
                "'dark' or 'light'"
            )

        # --------------------------------------------------------
        # Validate detection mode
        #
        # scanline = proven legacy behaviour (used by Wire Edge).
        # droplet  = Oil Edge enhancement; falls back to scanline
        #            when no convincing centered droplet is found.
        # --------------------------------------------------------

        detection_mode = str(
            detection_mode
        ).strip().lower()

        if detection_mode not in (
            "scanline",
            "droplet",
        ):
            raise ValueError(
                "edge detection mode must be "
                "'scanline' or 'droplet'"
            )

        # --------------------------------------------------------
        # Blur ringan
        #
        # Mengurangi noise kamera / kompresi DroidCam.
        # --------------------------------------------------------

        blurred = cv2.GaussianBlur(
            gray.payload,
            (
                5,
                5,
            ),
            0,
        )

        height = int(
            blurred.shape[0]
        )

        width = int(
            blurred.shape[1]
        )

        # --------------------------------------------------------
        # CENTRAL ROI
        #
        # Gunakan 80% bagian tengah gambar.
        #
        # Tujuannya supaya objek di ujung frame seperti meja,
        # monitor, kabel, border kamera, dll tidak terlalu mudah
        # dianggap sebagai drop.
        # --------------------------------------------------------

        x_start = int(
            width * 0.10
        )

        x_end = int(
            width * 0.90
        )

        y_start = int(
            height * 0.10
        )

        y_end = int(
            height * 0.90
        )

        if (
            x_end <= x_start
            or y_end <= y_start
        ):
            raise ValueError(
                "image ROI is too small"
            )

        roi = blurred[
            y_start:y_end,
            x_start:x_end,
        ]

        roi_height = int(
            roi.shape[0]
        )

        roi_width = int(
            roi.shape[1]
        )

        # --------------------------------------------------------
        # Helper: cari run foreground yang valid.
        #
        # Region yang menyentuh ujung ROI tidak diterima.
        # Ini penting supaya seluruh background gelap tidak
        # menghasilkan diameter = 640 pixel.
        # --------------------------------------------------------

        def valid_runs(
            values: Any,
        ) -> list[int]:

            if foreground == "dark":

                active = (
                    values
                    <= threshold
                )

            else:

                active = (
                    values
                    >= threshold
                )

            active_list = [
                bool(value)
                for value
                in active.tolist()
            ]

            runs: list[
                tuple[
                    int,
                    int,
                ]
            ] = []

            start: int | None = None

            for index, enabled in enumerate(
                active_list
            ):

                if enabled:

                    if start is None:
                        start = index

                elif start is not None:

                    runs.append(
                        (
                            start,
                            index - 1,
                        )
                    )

                    start = None

            if start is not None:

                runs.append(
                    (
                        start,
                        len(
                            active_list
                        ) - 1,
                    )
                )

            lengths: list[int] = []

            margin = 2

            for (
                run_start,
                run_end,
            ) in runs:

                length = (
                    run_end
                    - run_start
                    + 1
                )

                # Noise sangat kecil diabaikan.
                if length < 3:
                    continue

                # Jangan percaya object yang menyentuh border ROI.
                if (
                    run_start
                    <= margin
                    or run_end
                    >= (
                        len(
                            active_list
                        )
                        - 1
                        - margin
                    )
                ):
                    continue

                lengths.append(
                    length
                )

            return lengths

        # --------------------------------------------------------
        # MULTIPLE SCANLINES
        # --------------------------------------------------------

        diameter_candidates: list[
            float
        ] = []

        profile: list[
            float
        ]

        # ========================================================
        # HORIZONTAL SCAN
        #
        # Beberapa row di sekitar tengah ROI.
        # ========================================================

        if orientation == "horizontal":

            center = (
                roi_height
                // 2
            )

            band_half = max(
                2,
                int(
                    roi_height
                    * 0.15
                ),
            )

            sample_rows = np.linspace(
                max(
                    0,
                    center
                    - band_half,
                ),
                min(
                    roi_height
                    - 1,
                    center
                    + band_half,
                ),
                num=11,
                dtype=int,
            )

            sampled_profiles = []

            for row_index in sample_rows:

                scanline = roi[
                    int(
                        row_index
                    ),
                    :
                ]

                sampled_profiles.append(
                    scanline.astype(
                        np.float32
                    )
                )

                lengths = valid_runs(
                    scanline
                )

                if lengths:

                    diameter_candidates.append(
                        float(
                            max(
                                lengths
                            )
                        )
                    )

            if sampled_profiles:

                averaged = np.mean(
                    np.stack(
                        sampled_profiles,
                        axis=0,
                    ),
                    axis=0,
                )

                profile = [
                    float(
                        value
                    )
                    for value
                    in averaged.tolist()
                ]

            else:

                profile = []

        # ========================================================
        # VERTICAL SCAN
        #
        # Beberapa column di sekitar tengah ROI.
        # ========================================================

        else:

            center = (
                roi_width
                // 2
            )

            band_half = max(
                2,
                int(
                    roi_width
                    * 0.15
                ),
            )

            sample_columns = np.linspace(
                max(
                    0,
                    center
                    - band_half,
                ),
                min(
                    roi_width
                    - 1,
                    center
                    + band_half,
                ),
                num=11,
                dtype=int,
            )

            sampled_profiles = []

            for column_index in sample_columns:

                scanline = roi[
                    :,
                    int(
                        column_index
                    ),
                ]

                sampled_profiles.append(
                    scanline.astype(
                        np.float32
                    )
                )

                lengths = valid_runs(
                    scanline
                )

                if lengths:

                    diameter_candidates.append(
                        float(
                            max(
                                lengths
                            )
                        )
                    )

            if sampled_profiles:

                averaged = np.mean(
                    np.stack(
                        sampled_profiles,
                        axis=0,
                    ),
                    axis=0,
                )

                profile = [
                    float(
                        value
                    )
                    for value
                    in averaged.tolist()
                ]

            else:

                profile = []

        # --------------------------------------------------------
        # OIL DROPLET DETECTION (enhanced mode)
        #
        # Oil in a spinning-drop tube should appear as a compact/elongated
        # foreground component near the optical axis.  Instead of trusting
        # the longest dark run on each scanline, isolate connected contours,
        # reject border/large tube structures, and choose the most plausible
        # centered component.  The measured diameter follows the requested
        # scan orientation (vertical => droplet thickness).
        #
        # IMPORTANT: this path is only used when detection_mode="droplet".
        # Wire Edge keeps the proven scanline method.  If no convincing oil
        # contour is found, the legacy median scanline result below is used.
        # --------------------------------------------------------

        droplet_diameter_px: float | None = None
        droplet_center_x: float | None = None
        droplet_center_y: float | None = None
        droplet_threshold_used: float | None = None
        droplet_confidence: float | None = None
        droplet_major_axis_px: float | None = None
        droplet_minor_axis_px: float | None = None
        droplet_used_dynamic_roi = False

        if detection_mode == "droplet":

            # ----------------------------------------------------
            # PREVIOUS-TRACK STATE
            # ----------------------------------------------------

            previous_x: float | None = None
            previous_y: float | None = None
            previous_diameter: float | None = None

            if tracking_hint:
                try:
                    previous_x = float(
                        tracking_hint.get("center_x")
                    )
                    previous_y = float(
                        tracking_hint.get("center_y")
                    )
                    previous_diameter = float(
                        tracking_hint.get("diameter_px")
                    )
                except (TypeError, ValueError):
                    previous_x = None
                    previous_y = None
                    previous_diameter = None

            # ----------------------------------------------------
            # DYNAMIC ROI
            #
            # Search the full central ROI on first lock. Once a valid
            # track exists, search a smaller window around the previous
            # droplet. This reduces the chance of jumping to tube edges,
            # shadows, or other dark objects while still allowing motion.
            # Coordinates returned below remain relative to the original
            # central ROI so the existing tracking_hint contract is kept.
            # ----------------------------------------------------

            search_roi = roi
            search_offset_x = 0
            search_offset_y = 0

            if (
                previous_x is not None
                and previous_y is not None
                and previous_diameter is not None
                and previous_diameter > 0.0
                and math.isfinite(previous_x)
                and math.isfinite(previous_y)
                and math.isfinite(previous_diameter)
            ):
                half_width = int(
                    max(
                        roi_width * 0.22,
                        previous_diameter * 8.0,
                        40.0,
                    )
                )
                half_height = int(
                    max(
                        roi_height * 0.18,
                        previous_diameter * 6.0,
                        30.0,
                    )
                )

                dynamic_left = max(
                    0,
                    int(round(previous_x)) - half_width,
                )
                dynamic_right = min(
                    roi_width,
                    int(round(previous_x)) + half_width,
                )
                dynamic_top = max(
                    0,
                    int(round(previous_y)) - half_height,
                )
                dynamic_bottom = min(
                    roi_height,
                    int(round(previous_y)) + half_height,
                )

                if (
                    dynamic_right - dynamic_left >= 20
                    and dynamic_bottom - dynamic_top >= 20
                ):
                    search_roi = roi[
                        dynamic_top:dynamic_bottom,
                        dynamic_left:dynamic_right,
                    ]
                    search_offset_x = dynamic_left
                    search_offset_y = dynamic_top
                    droplet_used_dynamic_roi = True

            search_height = int(
                search_roi.shape[0]
            )
            search_width = int(
                search_roi.shape[1]
            )

            # ----------------------------------------------------
            # LIGHTING-ROBUST THRESHOLD CANDIDATES
            # ----------------------------------------------------

            threshold_candidates: list[tuple[str, float]] = [
                ("manual", threshold),
            ]

            otsu_flag = (
                cv2.THRESH_BINARY_INV
                if foreground == "dark"
                else cv2.THRESH_BINARY
            )
            otsu_value, _ = cv2.threshold(
                search_roi,
                0,
                255,
                otsu_flag | cv2.THRESH_OTSU,
            )

            if math.isfinite(float(otsu_value)):
                threshold_candidates.append(
                    ("otsu", float(otsu_value))
                )

            low_percentile = float(
                np.percentile(search_roi, 10.0)
            )
            high_percentile = float(
                np.percentile(search_roi, 70.0)
            )
            adaptive_value = (
                low_percentile + high_percentile
            ) / 2.0

            if math.isfinite(adaptive_value):
                threshold_candidates.append(
                    ("adaptive", adaptive_value)
                )

            unique_thresholds: list[tuple[str, float]] = []
            for source_name, candidate_threshold in threshold_candidates:
                candidate_threshold = max(
                    0.0,
                    min(255.0, float(candidate_threshold)),
                )
                if any(
                    abs(candidate_threshold - existing) < 2.0
                    for _, existing in unique_thresholds
                ):
                    continue
                unique_thresholds.append(
                    (source_name, candidate_threshold)
                )

            roi_center_x = roi_width / 2.0
            roi_center_y = roi_height / 2.0
            border_margin = 3
            minimum_area = max(
                12.0,
                search_width * search_height * 0.00003,
            )

            best_score: float | None = None
            best_dimension: float | None = None
            best_center: tuple[float, float] | None = None
            best_threshold: float | None = None
            best_confidence: float | None = None
            best_major_axis: float | None = None
            best_minor_axis: float | None = None

            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (3, 3),
            )

            for source_name, candidate_threshold in unique_thresholds:

                if foreground == "dark":
                    _, roi_binary = cv2.threshold(
                        search_roi,
                        candidate_threshold,
                        255,
                        cv2.THRESH_BINARY_INV,
                    )
                else:
                    _, roi_binary = cv2.threshold(
                        search_roi,
                        candidate_threshold,
                        255,
                        cv2.THRESH_BINARY,
                    )

                cleaned = cv2.morphologyEx(
                    roi_binary,
                    cv2.MORPH_OPEN,
                    kernel,
                    iterations=1,
                )
                cleaned = cv2.morphologyEx(
                    cleaned,
                    cv2.MORPH_CLOSE,
                    kernel,
                    iterations=1,
                )

                contours_result = cv2.findContours(
                    cleaned,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                contours = (
                    contours_result[0]
                    if len(contours_result) == 2
                    else contours_result[1]
                )

                for contour in contours:
                    area = float(
                        cv2.contourArea(contour)
                    )

                    if area < minimum_area:
                        continue

                    bx, by, bw, bh = cv2.boundingRect(
                        contour
                    )

                    if bw < 3 or bh < 3:
                        continue

                    if (
                        bx <= border_margin
                        or by <= border_margin
                        or bx + bw >= search_width - border_margin
                        or by + bh >= search_height - border_margin
                    ):
                        continue

                    if (
                        bw >= search_width * 0.82
                        or bh >= search_height * 0.82
                    ):
                        continue

                    extent = area / float(
                        max(bw * bh, 1)
                    )

                    if extent < 0.22:
                        continue

                    hull = cv2.convexHull(contour)
                    hull_area = float(
                        cv2.contourArea(hull)
                    )
                    solidity = (
                        area / hull_area
                        if hull_area > 0.0
                        else 0.0
                    )

                    # Shape validation: reject ragged / fragmented objects.
                    if solidity < 0.55:
                        continue

                    aspect_ratio = float(bw) / max(float(bh), 1.0)

                    # Spinning-drop oil can be round at low RPM and strongly
                    # elongated horizontally at high RPM. Only reject extreme
                    # shapes that are implausible for the intended droplet.
                    if aspect_ratio < 0.35 or aspect_ratio > 25.0:
                        continue

                    cx_local = bx + bw / 2.0
                    cy_local = by + bh / 2.0
                    cx = cx_local + search_offset_x
                    cy = cy_local + search_offset_y

                    normalized_dx = abs(
                        cx - roi_center_x
                    ) / max(
                        roi_width / 2.0,
                        1.0,
                    )
                    normalized_dy = abs(
                        cy - roi_center_y
                    ) / max(
                        roi_height / 2.0,
                        1.0,
                    )

                    # Keep the proven central-axis guards. Dynamic ROI already
                    # narrows the search after lock, but these remain a safety net.
                    if normalized_dy > 0.35:
                        continue

                    if normalized_dx > 0.48:
                        continue

                    bbox_dimension = float(
                        bw
                        if orientation == "horizontal"
                        else bh
                    )

                    # ------------------------------------------------
                    # ELLIPSE FITTING
                    # ------------------------------------------------
                    major_axis: float | None = None
                    minor_axis: float | None = None
                    ellipse_dimension: float | None = None

                    if len(contour) >= 5:
                        try:
                            _ellipse_center, axes, _angle = cv2.fitEllipse(
                                contour
                            )
                            axis_a = float(axes[0])
                            axis_b = float(axes[1])
                            major_axis = max(axis_a, axis_b)
                            minor_axis = min(axis_a, axis_b)

                            if (
                                math.isfinite(major_axis)
                                and math.isfinite(minor_axis)
                                and major_axis > 0.0
                                and minor_axis > 0.0
                            ):
                                ellipse_dimension = (
                                    major_axis
                                    if orientation == "horizontal"
                                    else minor_axis
                                )
                            else:
                                major_axis = None
                                minor_axis = None
                                ellipse_dimension = None
                        except (cv2.error, TypeError, ValueError):
                            major_axis = None
                            minor_axis = None
                            ellipse_dimension = None

                    # Use ellipse size when it agrees reasonably with the
                    # bounding-box measurement; otherwise keep the proven bbox.
                    dimension = bbox_dimension
                    ellipse_agrees = False

                    if ellipse_dimension is not None:
                        ratio = ellipse_dimension / max(bbox_dimension, 1.0)
                        if 0.55 <= ratio <= 1.35:
                            dimension = float(ellipse_dimension)
                            ellipse_agrees = True

                    area_bonus = min(
                        area / max(search_width * search_height * 0.01, 1.0),
                        1.0,
                    )

                    score = (
                        3.0 * normalized_dy
                        + 1.5 * normalized_dx
                        + (1.0 - min(extent, 1.0))
                        + 0.7 * (1.0 - min(solidity, 1.0))
                        - 0.35 * area_bonus
                    )

                    if source_name != "manual":
                        score += 0.05

                    track_distance = None
                    size_change = None

                    if (
                        previous_x is not None
                        and previous_y is not None
                    ):
                        track_dx = (cx - previous_x) / max(
                            roi_width,
                            1.0,
                        )
                        track_dy = (cy - previous_y) / max(
                            roi_height,
                            1.0,
                        )
                        track_distance = math.sqrt(
                            track_dx * track_dx
                            + track_dy * track_dy
                        )
                        score += 4.0 * track_distance

                    if (
                        previous_diameter is not None
                        and previous_diameter > 0
                    ):
                        size_change = abs(
                            dimension - previous_diameter
                        ) / max(previous_diameter, 1.0)
                        score += min(size_change, 2.0) * 0.65

                    # ------------------------------------------------
                    # CONFIDENCE SCORE (0..1)
                    # ------------------------------------------------
                    center_confidence = max(
                        0.0,
                        1.0 - min(
                            1.0,
                            normalized_dy / 0.35,
                        ) * 0.65
                        - min(
                            1.0,
                            normalized_dx / 0.48,
                        ) * 0.35,
                    )
                    shape_confidence = max(
                        0.0,
                        min(
                            1.0,
                            0.55 * min(solidity, 1.0)
                            + 0.45 * min(extent / 0.75, 1.0),
                        ),
                    )

                    tracking_confidence = 1.0
                    if track_distance is not None:
                        tracking_confidence = max(
                            0.0,
                            1.0 - min(track_distance / 0.20, 1.0),
                        )
                    if size_change is not None:
                        tracking_confidence *= max(
                            0.0,
                            1.0 - min(size_change / 0.60, 1.0) * 0.7,
                        )

                    ellipse_confidence = 1.0 if ellipse_agrees else 0.65
                    threshold_confidence = 1.0 if source_name == "manual" else 0.95

                    confidence = (
                        0.30 * center_confidence
                        + 0.30 * shape_confidence
                        + 0.25 * tracking_confidence
                        + 0.10 * ellipse_confidence
                        + 0.05 * threshold_confidence
                    )
                    confidence = max(
                        0.0,
                        min(1.0, confidence),
                    )

                    # A low-confidence candidate can still serve as fallback,
                    # but it must not beat a clearly stronger candidate solely
                    # because of a tiny geometry-score difference.
                    score += (1.0 - confidence) * 0.45

                    if (
                        best_score is None
                        or score < best_score
                    ):
                        best_score = score
                        best_dimension = dimension
                        best_center = (cx, cy)
                        best_threshold = candidate_threshold
                        best_confidence = confidence
                        best_major_axis = major_axis
                        best_minor_axis = minor_axis

            if (
                best_dimension is not None
                and math.isfinite(best_dimension)
                and best_dimension > 0
                and best_center is not None
            ):
                droplet_diameter_px = best_dimension
                droplet_center_x = float(best_center[0])
                droplet_center_y = float(best_center[1])
                droplet_threshold_used = best_threshold
                droplet_confidence = best_confidence
                droplet_major_axis_px = best_major_axis
                droplet_minor_axis_px = best_minor_axis

        # --------------------------------------------------------
        # Legacy scanline fallback / Wire Edge
        # --------------------------------------------------------

        if (
            droplet_diameter_px is None
            and not diameter_candidates
        ):

            raise ValueError(
                "no valid foreground object was found "
                "inside the central camera ROI"
            )

        if droplet_diameter_px is not None:
            diameter_px = float(
                droplet_diameter_px
            )
        else:
            # Proven legacy behaviour: median of scanline candidates.
            diameter_px = float(
                median(
                    diameter_candidates
                )
            )

        if (
            not math.isfinite(
                diameter_px
            )
            or diameter_px <= 0
        ):
            raise ValueError(
                "calculated diameter is invalid"
            )

        # --------------------------------------------------------
        # Edge / threshold image
        #
        # Tetap kompatibel dengan output lama.
        # --------------------------------------------------------

        if foreground == "dark":

            _, binary = (
                cv2.threshold(
                    blurred,
                    threshold,
                    255,
                    cv2.THRESH_BINARY_INV,
                )
            )

        else:

            _, binary = (
                cv2.threshold(
                    blurred,
                    threshold,
                    255,
                    cv2.THRESH_BINARY,
                )
            )

        return {
            "intensity_profile": profile,

            "edge_image": self._frame(
                binary
            ),

            "diameter_px": (
                diameter_px
            ),

            # Internal metadata used only by the Oil Edge handler for
            # temporal tracking. Existing graph outputs remain unchanged.
            "_droplet_center_x": droplet_center_x,
            "_droplet_center_y": droplet_center_y,
            "_droplet_threshold_used": droplet_threshold_used,
            "_droplet_confidence": droplet_confidence,
            "_droplet_major_axis_px": droplet_major_axis_px,
            "_droplet_minor_axis_px": droplet_minor_axis_px,
            "_droplet_dynamic_roi": droplet_used_dynamic_roi,
            "_raw_diameter_px": diameter_px,
        }

    # ============================================================
    # CANNY
    # ============================================================

    def canny(
        self,
        frame: ImageFrame,
        low: float,
        high: float,
    ) -> ImageFrame:

        frame = (
            self._require_frame(
                frame
            )
        )

        if not (
            0
            <= float(
                low
            )
            <= float(
                high
            )
        ):
            raise ValueError(
                "Canny thresholds must satisfy "
                "0 <= low <= high"
            )

        cv2, _ = (
            self._backends()
        )

        return self._frame(
            cv2.Canny(
                self.grayscale(
                    frame
                ).payload,
                low,
                high,
            )
        )

    # ============================================================
    # RESIZE
    # ============================================================

    def resize(
        self,
        frame: ImageFrame,
        width: int,
        height: int,
    ) -> ImageFrame:

        frame = (
            self._require_frame(
                frame
            )
        )

        width = int(
            width
        )

        height = int(
            height
        )

        if (
            width < 1
            or height < 1
            or width
            * height
            > MAX_IMAGE_PIXELS
        ):
            raise ValueError(
                "resize dimensions are outside bounds"
            )

        cv2, _ = (
            self._backends()
        )

        return self._frame(
            cv2.resize(
                frame.payload,
                (
                    width,
                    height,
                ),
            )
        )

    # ============================================================
    # TEMPLATE MATCH
    # ============================================================

    def template_match(
        self,
        frame: ImageFrame,
        template: ImageFrame,
    ) -> dict[str, Any]:

        frame = (
            self._require_frame(
                frame
            )
        )

        template = (
            self._require_frame(
                template
            )
        )

        if (
            frame.channels
            != template.channels
        ):
            raise ValueError(
                "template and source channels "
                "must match"
            )

        if (
            template.width
            > frame.width
            or template.height
            > frame.height
        ):
            raise ValueError(
                "template is larger than source image"
            )

        cv2, _ = (
            self._backends()
        )

        result = (
            cv2.matchTemplate(
                frame.payload,
                template.payload,
                cv2.TM_CCOEFF_NORMED,
            )
        )

        (
            _minimum,
            score,
            _minimum_location,
            location,
        ) = cv2.minMaxLoc(
            result
        )

        return {
            "score": float(
                score
            ),
            "x": int(
                location[0]
            ),
            "y": int(
                location[1]
            ),
        }

    # ============================================================
    # SAVE
    # ============================================================

    def save(
        self,
        frame: ImageFrame,
        path: Path,
    ) -> None:

        frame = (
            self._require_frame(
                frame
            )
        )

        cv2, _ = (
            self._backends()
        )

        if not cv2.imwrite(
            str(path),
            frame.payload,
        ):
            raise OSError(
                f"unable to save image: {path.name}"
            )

    # ============================================================
    # CLEANUP
    # ============================================================

    def __del__(
        self,
    ) -> None:

        try:
            self.release_all_captures()
        except Exception:
            pass