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

        self.capture: Any = None

        self.frame_lock = Lock()

        self.latest_frame: Any = None
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
    ) -> Any:

        if not self.frame_ready.wait(
            timeout
        ):
            raise OSError(
                "camera timed out waiting for first frame"
            )

        with self.frame_lock:

            if self.latest_frame is not None:

                return (
                    self.latest_frame.copy()
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

        if self.capture is not None:

            try:
                self.capture.release()
            except Exception:
                pass

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

            payload = worker.get_frame(
                timeout
            )

            return self._frame(
                payload
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

        payload = worker.get_frame(
            timeout
        )

        return self._frame(
            payload
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
        # Tidak ada kandidat
        # --------------------------------------------------------

        if not diameter_candidates:

            raise ValueError(
                "no valid foreground object was found "
                "inside the central camera ROI"
            )

        # --------------------------------------------------------
        # MEDIAN DIAMETER
        #
        # Lebih tahan terhadap satu scanline yang salah.
        # --------------------------------------------------------

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