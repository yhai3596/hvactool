from __future__ import annotations

import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Project
from .store import TaskStore


_STOP_TIMEOUT_SECONDS = 5.0


def _pid_by_port(port: int) -> int | None:
    """Find the PID listening on a local TCP port (Windows-only helper).

    Falls back to parsing netstat output if PowerShell is unavailable.
    """
    # Prefer Get-NetTCPConnection because netstat can be slow and its output
    # column alignment is locale-dependent.
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object -First 1 OwningProcess | ForEach-Object {{ $_.OwningProcess }}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        pid_text = result.stdout.strip().splitlines()[0].strip()
        return int(pid_text)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local = parts[1]
            state = parts[3].lower()
            if state != "listening":
                continue
            if local.endswith(f":{port}"):
                return int(parts[-1])
    except Exception:
        pass
    return None


def _stop_pid(pid: int, timeout: float = _STOP_TIMEOUT_SECONDS) -> tuple[bool, int | None]:
    """Gracefully terminate a PID, then force-kill if necessary.

    Returns (forced, return_code). Returns (False, None) if the process was
    already gone.
    """
    forced = False
    try:
        subprocess.run(["taskkill", "/PID", str(pid)], check=False, timeout=timeout)
        # taskkill sends WM_CLOSE and waits up to its own timeout; we then poll.
        for _ in range(int(timeout * 2)):
            try:
                check = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=1,
                )
                if str(pid) not in check.stdout:
                    return forced, None
            except Exception:
                pass
            import time
            time.sleep(0.5)
        forced = True
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, timeout=timeout)
        return forced, None
    except Exception:
        return forced, None


@dataclass(frozen=True)
class ProjectStatus:
    state: str
    detail: str


class ServiceManager:
    STOP_TIMEOUT_SECONDS = 5.0

    def __init__(self, projects: dict[str, Project], store: TaskStore, log_dir: Path):
        self.projects = projects
        self.store = store
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._active_tasks: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _executable_ready(command: tuple[str, ...]) -> bool:
        if not command:
            return False
        executable = Path(command[0])
        if executable.is_absolute():
            return executable.is_file()
        return shutil.which(command[0]) is not None

    @staticmethod
    def _probe(url: str) -> ProjectStatus:
        if not url:
            return ProjectStatus("not-applicable", "该模块没有 Web 健康检查")
        request = urllib.request.Request(url, headers={"User-Agent": "ECOER-Portal/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=1.2) as response:
                if 200 <= response.status < 500:
                    return ProjectStatus("online", f"HTTP {response.status}")
                return ProjectStatus("error", f"HTTP {response.status}")
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                return ProjectStatus("online", f"HTTP {error.code}，服务已响应且需要鉴权")
            if error.code == 404:
                return ProjectStatus("occupied", "端口已有服务响应，但健康端点不匹配")
            return ProjectStatus("error", f"HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, OSError):
            return ProjectStatus("offline", "未检测到服务")

    def status(self, project: Project) -> ProjectStatus:
        if not project.enabled:
            return ProjectStatus("disabled", "配置中已禁用")
        if not project.cwd.is_dir():
            return ProjectStatus("misconfigured", "项目目录不存在")
        if project.kind == "file":
            entry_file = project.resolved_entry_file()
            ready = entry_file is not None and entry_file.is_file()
            return ProjectStatus(
                "ready" if ready else "misconfigured",
                "独立看板文件可用" if ready else "独立看板文件不存在或路径无效",
            )
        if project.kind == "cli":
            interpreter = project.cwd / ".venv" / "Scripts" / "python.exe"
            ready = interpreter.is_file() or (project.cwd / "src").is_dir()
            return ProjectStatus(
                "ready" if ready else "misconfigured",
                "CLI 环境可用" if ready else "未找到 CLI 环境",
            )
        with self._lock:
            process = self._processes.get(project.id)
            task_id = self._active_tasks.get(project.id)
            return_code = process.poll() if process is not None else None
            if process is not None and return_code is not None:
                self._processes.pop(project.id, None)
                self._active_tasks.pop(project.id, None)
        if process is not None and return_code is not None:
            if task_id:
                self.store.update(
                    task_id,
                    "failed",
                    pid=process.pid,
                    message=f"服务进程已退出，exit code {return_code}",
                )
            return ProjectStatus("error", f"服务进程已退出，exit code {return_code}")
        status = self._probe(project.health_url)
        if status.state == "online" and task_id and process is not None:
            self.store.update(
                task_id,
                "running",
                pid=process.pid,
                message="服务已通过健康检查",
            )
            with self._lock:
                self._active_tasks.pop(project.id, None)
        elif status.state == "offline" and task_id and process is not None:
            return ProjectStatus("launching", "服务进程已启动，等待健康检查")
        return status

    def statuses(self) -> dict[str, ProjectStatus]:
        return {project_id: self.status(project) for project_id, project in self.projects.items()}

    def owns_process(self, project_id: str) -> bool:
        """Return whether this manager still owns a live child for the project."""
        with self._lock:
            process = self._processes.get(project_id)
            return process is not None and process.poll() is None

    def start(self, project_id: str) -> str:
        project = self.projects[project_id]
        task_id = self.store.create(project_id, "start", "queued")
        if not project.can_start:
            self.store.update(task_id, "rejected", message="该模块没有可启动的 Web 命令")
            return task_id
        current = self.status(project)
        if current.state == "online":
            self.store.update(task_id, "running", message="服务已经在线，没有重复启动")
            return task_id
        if current.state == "occupied":
            self.store.update(
                task_id,
                "rejected",
                message="端口已被其他服务占用，未执行启动",
            )
            return task_id
        if not project.cwd.is_dir():
            self.store.update(task_id, "failed", message="项目目录不存在")
            return task_id
        if not self._executable_ready(project.command):
            self.store.update(task_id, "failed", message="启动程序不存在或不在 PATH")
            return task_id

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.log_dir / f"{project.id}_{stamp}.log"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            with log_path.open("ab") as log_handle:
                process = subprocess.Popen(
                    list(project.command),
                    cwd=project.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    creationflags=creationflags,
                )
            with self._lock:
                self._processes[project.id] = process
                self._active_tasks[project.id] = task_id
            relative_log = log_path.name
            self.store.update(
                task_id,
                "launching",
                pid=process.pid,
                message=f"服务已启动，日志：var/logs/{relative_log}",
            )
        except OSError as error:
            self.store.update(task_id, "failed", message=f"启动失败：{error}")
        return task_id

    def stop(self, project_id: str) -> str:
        """Stop a project's service.

        If Portal started the process, terminate the known child. Otherwise fall
        back to killing whichever process is listening on the project's port.
        """
        project = self.projects.get(project_id)
        if project is None:
            task_id = self.store.create(project_id, "stop", "queued")
            self.store.update(task_id, "rejected", message="项目不存在")
            return task_id

        task_id = self.store.create(project_id, "stop", "queued")
        with self._lock:
            process = self._processes.get(project_id)
            start_task_id = self._active_tasks.get(project_id)
            owned_alive = process is not None and process.poll() is None

        if owned_alive:
            pid = process.pid
            forced = False
            try:
                process.terminate()
                try:
                    return_code = process.wait(timeout=self.STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    forced = True
                    process.kill()
                    return_code = process.wait(timeout=self.STOP_TIMEOUT_SECONDS)
            except (OSError, subprocess.SubprocessError) as error:
                self.store.update(
                    task_id,
                    "failed",
                    pid=pid,
                    message=f"停止失败：{error}",
                )
                return task_id

            with self._lock:
                if self._processes.get(project_id) is process:
                    self._processes.pop(project_id, None)
                if self._active_tasks.get(project_id) == start_task_id:
                    self._active_tasks.pop(project_id, None)
            if start_task_id:
                self.store.update(
                    start_task_id,
                    "stopped",
                    pid=pid,
                    message="服务在健康检查完成前由 Portal 停止",
                )
            method = "kill" if forced else "terminate"
            self.store.update(
                task_id,
                "completed",
                pid=pid,
                message=f"服务已停止（{method}，exit code {return_code}）",
            )
            return task_id

        # Portal does not own a live child; try to stop whatever is on the port.
        port = project.port
        if port is None:
            self.store.update(
                task_id,
                "rejected",
                message="项目未配置可识别的端口，无法定位外部进程",
            )
            return task_id

        pid = _pid_by_port(port)
        if pid is None:
            self.store.update(
                task_id,
                "rejected",
                message="端口未监听任何进程",
            )
            return task_id

        forced, _ = _stop_pid(pid, timeout=self.STOP_TIMEOUT_SECONDS)
        method = "强制结束" if forced else "正常结束"
        self.store.update(
            task_id,
            "completed",
            pid=pid,
            message=f"外部进程已停止（{method}，端口 {port}）",
        )
        return task_id

    def run_voc_classification(
        self,
        input_path: Path,
        output_path: Path,
        scope: str = "unlabeled",
    ) -> str:
        project = self.projects["voc"]
        task_id = self.store.create(project.id, "classify", "queued")
        interpreter = project.cwd / ".venv" / "Scripts" / "python.exe"
        if scope not in {"unlabeled", "all"}:
            self.store.update(task_id, "rejected", message="无效的分类范围")
            return task_id
        if not interpreter.is_file():
            self.store.update(task_id, "failed", message="VOC Python 环境不存在")
            return task_id

        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = (
            str(interpreter),
            "-m", "app", "classify-tickets",
            "--input", str(input_path),
            "--output", str(output_path),
            "--scope", scope,
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.log_dir / f"voc_{task_id[:8]}_{stamp}.log"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            with log_path.open("ab") as log_handle:
                process = subprocess.Popen(
                    list(command),
                    cwd=project.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    creationflags=creationflags,
                )
            self.store.update(
                task_id,
                "launching",
                pid=process.pid,
                message=f"VOC 分类已启动，日志：var/logs/{log_path.name}",
            )
        except OSError as error:
            self.store.update(task_id, "failed", message=f"VOC 启动失败：{error}")
            return task_id

        def monitor() -> None:
            return_code = process.wait()
            if return_code == 0 and output_path.is_file():
                self.store.update(
                    task_id,
                    "completed",
                    pid=process.pid,
                    message="VOC 分类完成，可下载结果文件",
                    artifact_path=str(output_path),
                )
            else:
                self.store.update(
                    task_id,
                    "failed",
                    pid=process.pid,
                    message=f"VOC 分类失败，exit code {return_code}；请查看日志 {log_path.name}",
                )

        threading.Thread(target=monitor, daemon=True).start()
        return task_id
