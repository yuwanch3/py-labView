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
    return (
        user_data_root()
        / "Captures"
    )


def measurement_exports_dir() -> Path:
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

    Existing folders are preserved and are never removed or overwritten.
    """

    directories = (
        user_data_root(),
        captures_dir(),
        measurement_exports_dir(),
        user_examples_dir(),
        projects_dir(),
    )

    for directory in directories:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    return directories


def copy_default_examples() -> tuple[Path, ...]:
    """
    Copy bundled default example projects into the user's Examples folder.

    Existing user files are preserved and are never overwritten.
    Missing bundled example files are skipped.
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

        if (
            not source.is_file()
            or destination.exists()
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
