from __future__ import annotations

import http.client
import re
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from support import PROJECT_ROOT, temporary_directory

from ecoer_portal.config import Project
from ecoer_portal.security import SessionManager
from ecoer_portal.services import ProjectStatus, ServiceManager
from ecoer_portal.store import TaskStore
from ecoer_portal.web import PortalApplication, make_server


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = temporary_directory()
        root = Path(self.temp.name)
        self.root = root
        (root / "src").mkdir()
        project = Project(
            id="voc",
            name="VOC",
            description="Test CLI",
            kind="cli",
            cwd=root,
            command=(),
            url="",
            health_url="",
            enabled=True,
            note="",
        )
        dashboard = root / "dashboard.html"
        dashboard.write_text(
            '<html><script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>'
            '<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>'
            '<script>        blobUrls[uuid] = URL.createObjectURL(new Blob([finalBytes], { type: entry.mime }));'
            '    document.documentElement.replaceWith(doc.documentElement);</script>Dashboard</html>',
            encoding="utf-8",
        )
        file_project = Project(
            id="dashboard",
            name="Dashboard",
            description="Test dashboard",
            kind="file",
            cwd=root,
            command=(),
            url="",
            health_url="",
            enabled=True,
            entry_file="dashboard.html",
        )
        web_project = Project(
            id="web-tool",
            name="Web Tool",
            description="Test web service",
            kind="web",
            cwd=root,
            command=("python", "server.py"),
            url="http://127.0.0.1:19090",
            health_url="http://127.0.0.1:19090/health",
            enabled=True,
        )
        self.web_project = web_project
        projects = {
            project.id: project,
            file_project.id: file_project,
            web_project.id: web_project,
        }
        store = TaskStore(root / "portal.db")
        self.store = store
        sessions = SessionManager("alan", "test-password")
        services = ServiceManager(projects, store, root / "logs")
        self.services = services
        app = PortalApplication(
            projects=projects,
            sessions=sessions,
            services=services,
            store=store,
            static_dir=PROJECT_ROOT / "src" / "ecoer_portal" / "static",
        )
        self.server = make_server(app, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: str | bytes = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, payload

    def login_cookie(self) -> str:
        body = urlencode({"username": "alan", "password": "test-password"})
        status, headers, _ = self.request(
            "POST",
            "/login",
            body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 303)
        cookie = SimpleCookie()
        cookie.load(headers["set-cookie"])
        return f"ecoer_portal_session={cookie['ecoer_portal_session'].value}"

    def test_health_is_public_and_dashboard_requires_login(self) -> None:
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn(b'"ok": true', body)
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login")

    def test_login_opens_dashboard_and_status_api(self) -> None:
        cookie = self.login_cookie()
        status, _, body = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("业务工具".encode(), body)
        status, _, body = self.request("GET", "/api/status", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b'"voc"', body)

    def test_post_requires_csrf(self) -> None:
        cookie = self.login_cookie()
        status, _, _ = self.request(
            "POST",
            "/projects/voc/start",
            "",
            {"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 403)

    def test_owned_online_web_service_shows_stop_and_routes_request(self) -> None:
        cookie = self.login_cookie()
        process = Mock(pid=654)
        process.poll.return_value = None
        self.services._processes[self.web_project.id] = process
        with patch.object(
            self.services,
            "_probe",
            return_value=ProjectStatus("online", "HTTP 200"),
        ):
            status, _, page = self.request("GET", "/", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertIn(b'data-stop-form>', page)
            self.assertIn(b'action="/projects/web-tool/stop"', page)

            status, _, api_body = self.request(
                "GET", "/api/status", headers={"Cookie": cookie}
            )
            self.assertEqual(status, 200)
            self.assertIn(b'"owned": true', api_body)

        csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page)
        self.assertIsNotNone(csrf)
        body = urlencode({"csrf_token": csrf.group(1).decode()})
        with patch.object(self.services, "stop", return_value="stop-task") as stop:
            status, headers, _ = self.request(
                "POST",
                "/projects/web-tool/stop",
                body,
                {
                    "Cookie": cookie,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/?task=stop-task")
        stop.assert_called_once_with("web-tool")

    def test_unowned_web_service_shows_stop_form(self) -> None:
        cookie = self.login_cookie()
        with patch.object(
            self.services,
            "_probe",
            return_value=ProjectStatus("online", "HTTP 200"),
        ):
            status, _, page = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertNotIn(b'data-stop-form hidden', page)
        self.assertIn(b'data-stop-form>', page)

    def test_owned_launching_web_service_shows_stop_form(self) -> None:
        cookie = self.login_cookie()
        process = Mock(pid=655)
        process.poll.return_value = None
        start_task_id = self.store.create(self.web_project.id, "start", "launching")
        self.services._processes[self.web_project.id] = process
        self.services._active_tasks[self.web_project.id] = start_task_id
        with patch.object(
            self.services,
            "_probe",
            return_value=ProjectStatus("offline", "not ready"),
        ):
            status, _, page = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b'data-stop-form>', page)
        self.assertIn("启动中".encode(), page)

    def test_cli_has_internal_entry_page(self) -> None:
        cookie = self.login_cookie()
        status, _, body = self.request("GET", "/projects/voc", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("可用工作流".encode(), body)
        self.assertIn(b"validate-rules", body)

    def test_file_dashboard_is_authenticated_and_allows_inline_bundle(self) -> None:
        status, _, _ = self.request("GET", "/projects/dashboard/open")
        self.assertEqual(status, 303)
        cookie = self.login_cookie()
        status, headers, body = self.request(
            "GET", "/projects/dashboard/open", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Dashboard", body)
        self.assertIn("'unsafe-inline'", headers["content-security-policy"])
        self.assertIn("'unsafe-eval'", headers["content-security-policy"])
        self.assertNotIn("https://unpkg.com", headers["content-security-policy"])
        self.assertNotIn(b'src="https://unpkg.com', body)
        self.assertIn(b"/static/vendor/react-18.3.1/react.production.min.js", body)
        self.assertIn("返回 ECOER Portal".encode(), body)
        self.assertIn(b'href=\\"/\\"', body)
        self.assertIn(b"new TextDecoder().decode(finalBytes)", body)
        self.assertIn(b"document.body.insertAdjacentHTML", body)

        status, _, vendor = self.request(
            "GET", "/static/vendor/react-18.3.1/react.production.min.js"
        )
        self.assertEqual(status, 200)
        self.assertGreater(len(vendor), 1000)

    def test_voc_upload_starts_fixed_background_command(self) -> None:
        cookie = self.login_cookie()
        status, _, page = self.request("GET", "/projects/voc", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page)
        self.assertIsNotNone(csrf)
        boundary = "----ecoer-test-boundary"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"csrf_token\"\r\n\r\n{csrf.group(1).decode()}\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"scope\"\r\n\r\nunlabeled\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"confirm\"\r\n\r\nyes\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"input_file\"; filename=\"sample.xlsx\"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n",
        ]
        body = "".join(parts).encode() + b"fake-xlsx-bytes\r\n" + f"--{boundary}--\r\n".encode()
        with patch.object(
            self.services, "run_voc_classification", return_value="task-123"
        ) as run:
            status, headers, _ = self.request(
                "POST",
                "/projects/voc/run",
                body,
                {
                    "Cookie": cookie,
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/projects/voc?task=task-123")
        input_path, output_path, scope = run.call_args.args
        self.assertTrue(input_path.is_file())
        self.assertTrue(output_path.is_relative_to(self.root / "outputs" / "voc"))
        self.assertEqual(scope, "unlabeled")

    def test_completed_voc_artifact_can_be_downloaded(self) -> None:
        output = self.root / "outputs" / "voc" / "result.xlsx"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"xlsx-result")
        task_id = self.store.create("voc", "classify", "launching")
        self.store.update(
            task_id,
            "completed",
            message="done",
            artifact_path=str(output),
        )
        cookie = self.login_cookie()
        status, headers, body = self.request(
            "GET", f"/tasks/{task_id}/download", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"xlsx-result")
        self.assertIn("attachment", headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
