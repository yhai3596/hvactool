from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str
    kind: str
    cwd: Path
    command: tuple[str, ...]
    url: str
    health_url: str
    enabled: bool
    note: str = ""
    entry_file: str = ""

    @property
    def can_start(self) -> bool:
        return self.enabled and self.kind == "web" and bool(self.command)

    @property
    def port(self) -> int | None:
        """Extract port from the project URL, if any."""
        parsed = urlparse(self.url)
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme == "http":
            return 80
        return None

    def resolved_entry_file(self) -> Path | None:
        if not self.entry_file:
            return None
        candidate = (self.cwd / self.entry_file).resolve()
        root = self.cwd.resolve()
        if not candidate.is_relative_to(root):
            return None
        return candidate


def _loopback_url(value: str, field: str, project_id: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError(f"{project_id}.{field} must be a local http URL")
    return value


def _project(raw: object) -> Project:
    if not isinstance(raw, dict):
        raise ValueError("Each project must be an object")
    project_id = str(raw.get("id", ""))
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError(f"Invalid project id: {project_id!r}")
    kind = str(raw.get("kind", ""))
    if kind not in {"web", "cli", "file"}:
        raise ValueError(f"Invalid project kind for {project_id}: {kind!r}")
    cwd = Path(str(raw.get("cwd", "")))
    if not cwd.is_absolute():
        raise ValueError(f"{project_id}.cwd must be an absolute path")
    command_raw = raw.get("command", [])
    if not isinstance(command_raw, list) or not all(
        isinstance(part, str) and part for part in command_raw
    ):
        raise ValueError(f"{project_id}.command must be a list of strings")
    entry_file = str(raw.get("entry_file", ""))
    if entry_file and Path(entry_file).is_absolute():
        raise ValueError(f"{project_id}.entry_file must be relative to cwd")
    return Project(
        id=project_id,
        name=str(raw.get("name", project_id)),
        description=str(raw.get("description", "")),
        kind=kind,
        cwd=cwd,
        command=tuple(command_raw),
        url=_loopback_url(str(raw.get("url", "")), "url", project_id),
        health_url=_loopback_url(
            str(raw.get("health_url", "")), "health_url", project_id
        ),
        enabled=bool(raw.get("enabled", True)),
        note=str(raw.get("note", "")),
        entry_file=entry_file,
    )


def load_projects(path: Path) -> dict[str, Project]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_projects = payload.get("projects") if isinstance(payload, dict) else None
    if not isinstance(raw_projects, list):
        raise ValueError("projects.json must contain a projects list")
    projects: dict[str, Project] = {}
    for raw in raw_projects:
        project = _project(raw)
        if project.id in projects:
            raise ValueError(f"Duplicate project id: {project.id}")
        projects[project.id] = project
    if not projects:
        raise ValueError("At least one project must be configured")
    return projects
