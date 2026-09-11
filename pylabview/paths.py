from __future__ import annotations

import shutil
import sys
from pathlib import Path


APP_NAME = "GMJ PyLabView"


def application_resource_root() -> Path:
    """
    Return the root directory that contains bundled application resources.

    Source mode:
        <project root>

    PyInstaller one-file / frozen mode:
        sys._MEIPASS
    """

    if getattr(sys, "frozen", False):
        bundle_root = getattr(
            sys,
            "_MEIPASS",
            None,
        )

        if bundle_root:
            return Path(
                bundle_root
            ).resolve()

    return (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )


def user_documents_root() -> Path:
    """
    Return the user's Documents directory.

    Writable application data is kept separate from bundled resources.
    """

    return (
        Path.home()
        / "Documents"
    )


def user_data_root() -> Path:
    return (
        user_documents_root()
        / APP_NAME
    )


def captures_dir() -> Path:
    """
    Legacy captures directory.

    Existing behaviour is preserved. New session-based capture paths
    are provided separately below and are not activated here.
    """

    return (
        user_data_root()
        / "Captures"
    )


def measurement_exports_dir() -> Path:
    """
    Legacy measurement-export directory.

    Existing behaviour is preserved. New session-based measurement paths
    are provided separately below and are not activated here.
    """

    return (
        user_data_root()
        / "Measurement Exports"
    )


def user_examples_dir() -> Path:
    return (
        user_data_root()
        / "Examples"
    )


def projects_dir() -> Path:
    return (
        user_data_root()
        / "Projects"
    )


# ================================================================
# SESSION PATH INFRASTRUCTURE
#
# IMPORTANT:
# These helpers only describe the new folder structure.
# They do NOT create a session automatically and do NOT redirect any
# existing capture/export workflow yet.
# ================================================================

def sessions_dir() -> Path:
    return (
        user_data_root()
        / "Sessions"
    )


def session_dir(
    session_name: str,
) -> Path:
    return (
        sessions_dir()
        / session_name
    )


def session_captures_dir(
    session_root: Path,
) -> Path:
    return (
        session_root
        / "Captures"
    )


def session_reference_dir(
    session_root: Path,
) -> Path:
    return (
        session_captures_dir(
            session_root
        )
        / "Reference"
    )


def session_stages_dir(
    session_root: Path,
) -> Path:
    return (
        session_captures_dir(
            session_root
        )
        / "Stages"
    )


def session_stage_dir(
    session_root: Path,
    rpm: int,
) -> Path:
    return (
        session_stages_dir(
            session_root
        )
        / f"{int(rpm)}_RPM"
    )


def session_analysis_dir(
    session_root: Path,
) -> Path:
    return (
        session_captures_dir(
            session_root
        )
        / "Analysis"
    )


def session_analysis_rpm_dir(
    session_root: Path,
    rpm: int,
) -> Path:
    return (
        session_analysis_dir(
            session_root
        )
        / f"{int(rpm)}_RPM"
    )


def session_measurements_dir(
    session_root: Path,
) -> Path:
    return (
        session_root
        / "Measurements"
    )


def session_info_path(
    session_root: Path,
) -> Path:
    return (
        session_root
        / "Session_Info.json"
    )


def bundled_assets_dir() -> Path:
    return (
        application_resource_root()
        / "assets"
    )


def bundled_examples_dir() -> Path:
    return (
        application_resource_root()
        / "examples"
    )


def bundled_docs_dir() -> Path:
    return (
        application_resource_root()
        / "docs"
    )


def ensure_user_directories() -> tuple[Path, ...]:
    """
    Create the writable user-data directory structure if needed.

    Existing folders are preserved and are never removed.

    Legacy top-level Captures and Measurement Exports folders are no longer
    created. Capture and measurement output belongs to the active Session.
    Individual session folders are intentionally NOT created in paths.py.
    """

    directories = (
        user_data_root(),
        user_examples_dir(),
        projects_dir(),
        sessions_dir(),
    )

    for directory in directories:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    return directories


def copy_default_examples() -> tuple[Path, ...]:
    """
    Sync bundled default example projects into the user's Examples folder.

    The two application-managed default examples are refreshed from the
    bundled release when their contents differ, so users do not keep stale
    Standard/Manual examples after an application update. Missing bundled
    example files are skipped.
    """

    source_dir = bundled_examples_dir()
    destination_dir = user_examples_dir()

    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filenames = (
        "spinning_drop_ift.json",
        "spinning_drop_manual_ift.json",
    )

    copied: list[Path] = []

    for filename in filenames:
        source = (
            source_dir
            / filename
        )

        destination = (
            destination_dir
            / filename
        )

        if not source.is_file():
            continue

        if (
            destination.exists()
            and source.read_bytes()
            == destination.read_bytes()
        ):
            continue

        shutil.copy2(
            source,
            destination,
        )

        copied.append(
            destination
        )

    return tuple(
        copied
    )
