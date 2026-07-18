from __future__ import annotations

import subprocess
import sys
import unittest
import urllib.error
import time
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from support import temporary_directory

from ecoer_portal.config import Project
from ecoer_portal.services import ProjectStatus, ServiceManager
from ecoer_portal.store import TaskStore


class ServiceTests(unittest.TestCase):
    def test_probe_marks_404_as_occupied(self) -> None:
        error = urllib.error.HTTPError(
            "http://127.0.0.1:9000/health", 404, "Not Found", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=error):
            status = ServiceManager._probe("http://127.0.0.1:9000/health")
        self.assertEqual(status.state, "occupied")

    def test_start_rejects_occupied_port(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample",
                "Sample",
                "",
                "web",
                root,
                ("python", "server.py"),
                "http://127.0.0.1:9000",
                "http://127.0.0.1:9000/health",
                True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")
            with patch.object(
                manager,
                "status",
                return_value=ProjectStatus("occupied", "health mismatch"),
            ):
                manager.start(project.id)
            task = store.recent()[0]
            self.assertEqual(task["status"], "rejected")
            self.assertIn("端口", str(task["message"]))

    def test_alive_process_reports_launching_until_health_is_ready(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample", "Sample", "", "web", root,
                ("python", "server.py"),
                "http://127.0.0.1:9000", "http://127.0.0.1:9000/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")
            task_id = store.create(project.id, "start", "launching")
            manager._processes[project.id] = SimpleNamespace(poll=lambda: None, pid=321)  # type: ignore[assignment]
            manager._active_tasks[project.id] = task_id
            with patch.object(
                manager,
                "_probe",
                return_value=ProjectStatus("offline", "not ready"),
            ):
                status = manager.status(project)
            self.assertEqual(status.state, "launching")

    def test_stop_terminates_only_the_owned_project_process(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            first = Project(
                "first", "First", "", "web", root,
                ("python", "server.py"), "http://127.0.0.1:9000",
                "http://127.0.0.1:9000/health", True,
            )
            second = Project(
                "second", "Second", "", "web", root,
                ("python", "server.py"), "http://127.0.0.1:9001",
                "http://127.0.0.1:9001/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager(
                {first.id: first, second.id: second}, store, root / "logs"
            )
            target = Mock(pid=111)
            target.poll.return_value = None
            target.wait.return_value = 0
            untouched = Mock(pid=222)
            untouched.poll.return_value = None
            manager._processes[first.id] = target
            manager._processes[second.id] = untouched

            task_id = manager.stop(first.id)

            target.terminate.assert_called_once_with()
            target.kill.assert_not_called()
            untouched.terminate.assert_not_called()
            self.assertFalse(manager.owns_process(first.id))
            self.assertTrue(manager.owns_process(second.id))
            task = store.get(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["pid"], 111)

    def test_stop_kills_owned_process_after_terminate_timeout(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample", "Sample", "", "web", root,
                ("python", "server.py"), "http://127.0.0.1:9000",
                "http://127.0.0.1:9000/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")
            process = Mock(pid=333)
            process.poll.return_value = None
            process.wait.side_effect = [
                subprocess.TimeoutExpired("sample", manager.STOP_TIMEOUT_SECONDS),
                -9,
            ]
            manager._processes[project.id] = process

            task_id = manager.stop(project.id)

            process.terminate.assert_called_once_with()
            process.kill.assert_called_once_with()
            task = store.get(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertIn("kill", str(task["message"]))

    def test_stop_rejects_when_no_owned_process_and_port_is_free(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample", "Sample", "", "web", root,
                ("python", "server.py"), "http://127.0.0.1:9000",
                "http://127.0.0.1:9000/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")

            with patch("ecoer_portal.services._pid_by_port", return_value=None):
                task_id = manager.stop(project.id)

            task = store.get(task_id)
            self.assertEqual(task["status"], "rejected")
            self.assertIn("端口未监听", str(task["message"]))

    def test_stop_falls_back_to_port_when_not_owned(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample", "Sample", "", "web", root,
                ("python", "server.py"), "http://127.0.0.1:9000",
                "http://127.0.0.1:9000/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")

            with patch("ecoer_portal.services._pid_by_port", return_value=7777):
                with patch("ecoer_portal.services._stop_pid", return_value=(False, None)):
                    task_id = manager.stop(project.id)

            task = store.get(task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["pid"], 7777)
            self.assertIn("外部进程已停止", str(task["message"]))

    def test_project_port_extracted_from_url(self) -> None:
        project = Project(
            "sample", "Sample", "", "web", Path("/tmp"),
            ("python", "server.py"), "http://127.0.0.1:8123",
            "http://127.0.0.1:8123/health", True,
        )
        self.assertEqual(project.port, 8123)

    def test_start_then_stop_real_child_process(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            project = Project(
                "sample", "Sample", "", "web", root,
                (sys.executable, "-c", "import time; time.sleep(60)"),
                "http://127.0.0.1:9", "http://127.0.0.1:9/health", True,
            )
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")
            process = None
            try:
                manager.start(project.id)
                process = manager._processes[project.id]
                self.assertTrue(manager.owns_process(project.id))

                stop_task_id = manager.stop(project.id)

                self.assertIsNotNone(process.poll())
                self.assertFalse(manager.owns_process(project.id))
                stop_task = store.get(stop_task_id)
                self.assertEqual(stop_task["status"], "completed")
                self.assertEqual(stop_task["pid"], process.pid)
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_voc_background_task_completes_with_artifact(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            interpreter = root / ".venv" / "Scripts" / "python.exe"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"")
            project = Project("voc", "VOC", "", "cli", root, (), "", "", True)
            store = TaskStore(root / "portal.db")
            manager = ServiceManager({project.id: project}, store, root / "logs")
            input_path = root / "input.xlsx"
            output_path = root / "output.xlsx"
            input_path.write_bytes(b"input")
            output_path.write_bytes(b"output")
            fake_process = SimpleNamespace(pid=456, wait=lambda: 0)
            with patch("subprocess.Popen", return_value=fake_process):
                task_id = manager.run_voc_classification(input_path, output_path)
            for _ in range(50):
                task = store.get(task_id)
                if task and task["status"] == "completed":
                    break
                time.sleep(0.01)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["artifact_path"], str(output_path))


if __name__ == "__main__":
    unittest.main()
