"""Process-wide singletons wired together in main.create_app()."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .collect import CollectManager
from .download import DownloadManager
from .platforms.registry import PlatformRegistry
from .storage.db import Database
from .storage.raw import RawStore
from .tasks.manager import TaskManager
from .ws.hub import ExtensionHub


@dataclass
class AppState:
    settings: Settings
    token: str
    registry: PlatformRegistry
    db: Database
    raw: RawStore
    hub: ExtensionHub
    tasks: TaskManager
    downloads: DownloadManager
    collects: CollectManager
