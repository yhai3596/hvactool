from __future__ import annotations

import html
import json
import mimetypes
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from .config import Project
from .security import Session, SessionManager
from .services import ProjectStatus, ServiceManager
from .store import TaskStore


SESSION_COOKIE = "ecoer_portal_session"


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · ECOER Portal</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>{body}<script src="/static/app.js"></script></body>
</html>"""
    return document.encode("utf-8")


def _badge(status: ProjectStatus) -> str:
    labels = {
        "online": "在线",
        "offline": "未启动",
        "ready": "可用",
        "launching": "启动中",
        "disabled": "已禁用",
        "misconfigured": "配置异常",
        "occupied": "端口占用",
        "error": "异常",
        "not-applicable": "无需检测",
    }
    label = labels.get(status.state, status.state)
    return (
        f'<span class="badge badge-{html.escape(status.state)}" '
        f'data-status>{html.escape(label)}</span>'
    )


def _project_card(
    project: Project,
    status: ProjectStatus,
    csrf_token: str,
) -> str:
    action = ""
    if project.kind == "web":
        button_labels = {
            "online": "已在线",
            "launching": "启动中…",
            "occupied": "端口占用",
        }
        start_label = button_labels.get(status.state, "启动服务")
        start_allowed = project.can_start and status.state not in {
            "online", "launching", "occupied", "disabled", "misconfigured"
        }
        start_disabled = "" if start_allowed else " disabled"
        open_allowed = bool(project.url) and status.state == "online"
        open_disabled = "" if open_allowed else " disabled"
        open_href = html.escape(project.url or "#", quote=True)
        stop_allowed = project.can_start and status.state in {"online", "launching", "occupied"}
        stop_hidden = "" if stop_allowed else " hidden"
        stop_action = ""
        if project.can_start:
            stop_action = f"""
          <form method="post" action="/projects/{project.id}/stop" data-stop-form{stop_hidden}>
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">
            <button class="button button-danger" type="submit" data-stop-button>停止服务</button>
          </form>"""
        action = f"""
        <div class="card-actions">
          <form method="post" action="/projects/{project.id}/start" data-start-form>
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">
            <button class="button button-secondary" type="submit" data-start-button{start_disabled}>{html.escape(start_label)}</button>
          </form>
          {stop_action}
          <a class="button button-primary{open_disabled}" data-open-link href="{open_href}" target="_blank" rel="noopener">打开工具</a>
        </div>"""
    elif project.kind == "cli":
        action = f'<div class="card-actions"><a class="button button-primary" href="/projects/{project.id}">进入模块</a></div>'
    elif project.kind == "file":
        open_disabled = "" if status.state == "ready" else " disabled"
        action = (
            f'<div class="card-actions"><a class="button button-primary{open_disabled}" '
            f'href="/projects/{project.id}/open" target="_blank" rel="noopener">打开独立看板</a></div>'
        )
    else:
        action = '<div class="card-actions"><span class="muted">暂无入口</span></div>'
    note = f'<p class="note">{html.escape(project.note)}</p>' if project.note else ""
    return f"""
    <article class="project-card" data-project-id="{html.escape(project.id)}">
      <div class="card-top"><span class="eyebrow">{html.escape(project.kind.upper())}</span>{_badge(status)}</div>
      <h2>{html.escape(project.name)}</h2>
      <p>{html.escape(project.description)}</p>
      {note}
      <div class="status-detail" data-status-detail>{html.escape(status.detail)}</div>
      {action}
    </article>"""


def _tasks_rows(tasks: list[dict[str, object]], projects: dict[str, Project]) -> str:
    if not tasks:
        return '<tr><td colspan="5" class="empty">还没有启动记录</td></tr>'
    rows = []
    for task in tasks:
        project = projects.get(str(task["project_id"]))
        name = project.name if project else str(task["project_id"])
        artifact = str(task.get("artifact_path") or "")
        download = (
            f' <a class="task-download" href="/tasks/{html.escape(str(task["id"]))}/download">下载结果</a>'
            if artifact and str(task.get("status")) == "completed"
            else ""
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(str(task['action']))}</td>"
            f"<td><span class=\"task-status\">{html.escape(str(task['status']))}</span>{download}</td>"
            f"<td>{html.escape(str(task.get('message') or ''))}</td>"
            f"<td>{html.escape(str(task['created_at']))}</td>"
            "</tr>"
        )
    return "".join(rows)


class PortalApplication:
    def __init__(
        self,
        *,
        projects: dict[str, Project],
        sessions: SessionManager,
        services: ServiceManager,
        store: TaskStore,
        static_dir: Path,
        secure_cookie: bool = False,
    ):
        self.projects = projects
        self.sessions = sessions
        self.services = services
        self.store = store
        self.static_dir = static_dir.resolve()
        self.secure_cookie = secure_cookie

    @staticmethod
    def _cookie_token(handler: BaseHTTPRequestHandler) -> str | None:
        cookie = SimpleCookie()
        cookie.load(handler.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    @staticmethod
    def _form(handler: BaseHTTPRequestHandler) -> dict[str, str]:
        length = int(handler.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            raise ValueError("Request body is too large")
        body = handler.rfile.read(length).decode("utf-8")
        return {key: values[-1] for key, values in parse_qs(body).items()}

    @staticmethod
    def _multipart(
        handler: BaseHTTPRequestHandler,
    ) -> tuple[dict[str, str], str, bytes]:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0 or length > 30 * 1024 * 1024:
            raise ValueError("上传文件必须小于 30 MB")
        content_type = handler.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("请求必须使用 multipart/form-data")
        body = handler.rfile.read(length)
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + body
        )
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        fields: dict[str, str] = {}
        filename = ""
        file_bytes = b""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition") or ""
            part_filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if name == "input_file" and part_filename:
                filename = Path(part_filename).name
                file_bytes = payload
            elif name:
                fields[name] = payload.decode("utf-8", errors="replace")
        if not filename or not file_bytes:
            raise ValueError("请选择需要分类的 Excel 文件")
        return fields, filename, file_bytes

    @staticmethod
    def _send(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes = b"",
        *,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
        content_security_policy: str | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Referrer-Policy", "same-origin")
        handler.send_header(
            "Content-Security-Policy",
            content_security_policy
            or "default-src 'self'; style-src 'self'; script-src 'self'; "
               "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        if body:
            handler.wfile.write(body)

    def _redirect(self, handler: BaseHTTPRequestHandler, location: str) -> None:
        self._send(handler, HTTPStatus.SEE_OTHER, headers={"Location": location})

    def _json(self, handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(handler, status, body, content_type="application/json; charset=utf-8")

    def _session(self, handler: BaseHTTPRequestHandler) -> Session | None:
        return self.sessions.get(self._cookie_token(handler))

    def _require_session(
        self, handler: BaseHTTPRequestHandler, *, api: bool = False
    ) -> Session | None:
        session = self._session(handler)
        if session:
            return session
        if api:
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "login_required"})
        else:
            self._redirect(handler, "/login")
        return None

    def _login_page(self, error: str = "") -> bytes:
        error_html = f'<div class="alert">{html.escape(error)}</div>' if error else ""
        return _page(
            "登录",
            f"""
            <main class="login-shell">
              <section class="login-panel">
                <div class="brand-mark">E</div>
                <p class="eyebrow">ECOER INTERNAL TOOLS</p>
                <h1>统一工作台</h1>
                <p class="login-copy">一个入口查看 ECOER 数据、分析、VOC 与工程工具。</p>
                {error_html}
                <form method="post" action="/login" class="login-form">
                  <label>用户名<input name="username" autocomplete="username" required autofocus></label>
                  <label>密码<input type="password" name="password" autocomplete="current-password" required></label>
                  <button class="button button-primary button-wide" type="submit">登录工作台</button>
                </form>
                <p class="security-note">本地 MVP · 默认仅监听 127.0.0.1</p>
              </section>
            </main>""",
        )

    def _task_notice(self, task_id: str) -> str:
        if not task_id:
            return ""
        task = self.store.get(task_id)
        if not task:
            return '<div class="alert">未找到本次启动记录。</div>'
        project = self.projects.get(str(task["project_id"]))
        project_name = project.name if project else str(task["project_id"])
        return (
            '<div class="launch-notice" data-task-notice>'
            f'<strong>{html.escape(project_name)}</strong>：'
            f'<span>{html.escape(str(task["status"]))}</span> · '
            f'{html.escape(str(task.get("message") or "启动请求已提交"))}'
            '</div>'
        )

    def _enriched_tasks(self) -> list[dict[str, object]]:
        tasks = self.store.recent()
        for task in tasks:
            project = self.projects.get(str(task["project_id"]))
            task["project_name"] = project.name if project else str(task["project_id"])
        return tasks

    def _api_tasks(self) -> list[dict[str, object]]:
        tasks = self._enriched_tasks()
        for task in tasks:
            task["has_artifact"] = bool(task.pop("artifact_path", ""))
        return tasks

    def _dashboard(self, session: Session, task_id: str = "") -> bytes:
        statuses = self.services.statuses()
        cards = "".join(
            _project_card(
                project,
                statuses[project.id],
                session.csrf_token,
            )
            for project in self.projects.values()
        )
        online = sum(status.state in {"online", "ready"} for status in statuses.values())
        tasks = self._enriched_tasks()
        return _page(
            "工作台",
            f"""
            <header class="topbar">
              <div><span class="logo">ECOER</span><span class="topbar-subtitle">AI & Data Workspace</span></div>
              <form method="post" action="/logout">
                <input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">
                <button class="text-button" type="submit">退出</button>
              </form>
            </header>
            <main class="dashboard">
              {self._task_notice(task_id)}
              <section class="hero">
                <div><p class="eyebrow">CONTROL CENTER</p><h1>早上好，{html.escape(session.username)}</h1>
                <p>集中启动、查看和进入 ECOER 内部工具。</p></div>
                <div class="metric"><strong>{online}/{len(statuses)}</strong><span>模块可用</span></div>
              </section>
              <section class="section-heading"><div><p class="eyebrow">TOOLS</p><h2>业务工具</h2></div>
                <span class="poll-note">启动期间每 2 秒自动刷新状态</span></section>
              <section class="project-grid">{cards}</section>
              <section class="tasks-section">
                <div class="section-heading"><div><p class="eyebrow">ACTIVITY</p><h2>最近启动记录</h2></div></div>
                <div class="table-wrap"><table><thead><tr><th>模块</th><th>动作</th><th>状态</th><th>说明</th><th>时间（UTC）</th></tr></thead>
                <tbody id="task-rows">{_tasks_rows(tasks, self.projects)}</tbody></table></div>
              </section>
            </main>
            <footer>Portal 只负责控制与状态，不改写现有项目业务数据。</footer>""",
        )

    def _cli_project_page(
        self,
        session: Session,
        project: Project,
        *,
        task_id: str = "",
        error: str = "",
    ) -> bytes:
        status = self.services.status(project)
        commands = [
            ("校验分类规则", r".\.venv\Scripts\python.exe -m app validate-rules"),
            ("分类新工单", r".\.venv\Scripts\python.exe -m app classify-tickets --input .\_data\new_tickets.xlsx --output .\_data\new_tickets_classified.xlsx"),
            ("运行一键分类", r"powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_classification.ps1 -InputFile .\_data\new_tickets.xlsx"),
        ]
        command_cards = "".join(
            f'<article class="command-card"><h3>{html.escape(label)}</h3><code>{html.escape(command)}</code></article>'
            for label, command in commands
        )
        error_html = f'<div class="alert">{html.escape(error)}</div>' if error else ""
        voc_tasks = [
            task for task in self._enriched_tasks()
            if str(task.get("project_id")) == project.id
        ]
        return _page(
            project.name,
            f"""
            <header class="topbar"><div><a class="logo logo-link" href="/">ECOER</a><span class="topbar-subtitle">VOC Workspace</span></div>
              <form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}"><button class="text-button" type="submit">退出</button></form></header>
            <main class="dashboard detail-page">
              <a class="back-link" href="/">← 返回统一工作台</a>
              {self._task_notice(task_id)}
              <section class="detail-hero"><div><p class="eyebrow">CLI WORKFLOW</p><h1>{html.escape(project.name)}</h1><p>{html.escape(project.description)}</p></div>{_badge(status)}</section>
              {error_html}
              <section class="voc-run-panel">
                <div><p class="eyebrow">RUN CLASSIFICATION</p><h2>直接运行 VOC 分类</h2><p>上传 `.xlsx`，Portal 会复制输入文件、后台调用现有模型，并生成新的结果文件。</p></div>
                <form method="post" action="/projects/voc/run" enctype="multipart/form-data" class="voc-form">
                  <input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">
                  <label>输入 Excel<input type="file" name="input_file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required></label>
                  <label>分类范围<select name="scope"><option value="unlabeled">仅分类空白 Ticket Type1（推荐）</option><option value="all">重新分类全部行</option></select></label>
                  <label class="confirm-row"><input type="checkbox" name="confirm" value="yes" required> 我确认输出为新文件，不覆盖上传源文件</label>
                  <button class="button button-primary" type="submit">上传并开始分类</button>
                </form>
              </section>
              <section class="section-heading"><div><p class="eyebrow">ACTIVITY</p><h2>VOC 运行记录</h2></div><span class="poll-note">每 2 秒刷新</span></section>
              <div class="table-wrap"><table><thead><tr><th>模块</th><th>动作</th><th>状态</th><th>说明</th><th>时间（UTC）</th></tr></thead><tbody id="task-rows" data-project-filter="voc">{_tasks_rows(voc_tasks, self.projects)}</tbody></table></div>
              <section class="section-heading"><div><p class="eyebrow">COMMANDS</p><h2>可用工作流</h2></div></section>
              <section class="command-grid">{command_cards}</section>
              <p class="muted">项目目录：{html.escape(str(project.cwd))}</p>
            </main>""",
        )

    def _run_voc_upload(
        self,
        handler: BaseHTTPRequestHandler,
        session: Session,
    ) -> None:
        project = self.projects.get("voc")
        if project is None:
            self._send(handler, HTTPStatus.NOT_FOUND, b"VOC project not configured", content_type="text/plain")
            return
        try:
            fields, filename, file_bytes = self._multipart(handler)
            if not self.sessions.csrf_valid(session, fields.get("csrf_token", "")):
                self._send(handler, HTTPStatus.FORBIDDEN, b"Invalid CSRF token", content_type="text/plain")
                return
            if fields.get("confirm") != "yes":
                raise ValueError("请确认不会覆盖上传源文件")
            if Path(filename).suffix.lower() != ".xlsx":
                raise ValueError("只允许上传 .xlsx 文件")
            scope = fields.get("scope", "unlabeled")
            if scope not in {"unlabeled", "all"}:
                raise ValueError("无效的分类范围")
            run_id = uuid4().hex
            upload_dir = self.store.path.parent / "uploads" / "voc"
            output_dir = self.store.path.parent / "outputs" / "voc"
            upload_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            input_path = upload_dir / f"{run_id}_input.xlsx"
            output_path = output_dir / f"{Path(filename).stem}_classified_{run_id[:8]}.xlsx"
            input_path.write_bytes(file_bytes)
            task_id = self.services.run_voc_classification(input_path, output_path, scope)
            self._redirect(handler, f"/projects/voc?task={task_id}")
        except ValueError as error:
            self._send(
                handler,
                HTTPStatus.BAD_REQUEST,
                self._cli_project_page(session, project, error=str(error)),
            )

    def _serve_artifact(self, handler: BaseHTTPRequestHandler, task_id: str) -> None:
        task = self.store.get(task_id)
        if not task or str(task.get("status")) != "completed":
            self._send(handler, HTTPStatus.NOT_FOUND, b"Completed artifact not found", content_type="text/plain")
            return
        artifact = Path(str(task.get("artifact_path") or "")).resolve()
        output_root = (self.store.path.parent / "outputs").resolve()
        if not artifact.is_relative_to(output_root) or not artifact.is_file():
            self._send(handler, HTTPStatus.FORBIDDEN, b"Artifact path is not allowed", content_type="text/plain")
            return
        content_type = mimetypes.guess_type(artifact.name)[0] or "application/octet-stream"
        self._send(
            handler,
            HTTPStatus.OK,
            artifact.read_bytes(),
            content_type=content_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="voc-result-{task_id[:8]}.xlsx"; '
                    f"filename*=UTF-8''{quote(artifact.name)}"
                ),
                "Cache-Control": "no-store",
            },
        )

    def _serve_project_file(self, handler: BaseHTTPRequestHandler, project: Project) -> None:
        target = project.resolved_entry_file()
        if target is None or not target.is_file():
            self._send(handler, HTTPStatus.NOT_FOUND, b"Dashboard file not found", content_type="text/plain")
            return
        content = target.read_text(encoding="utf-8")
        content = content.replace(
            "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
            "/static/vendor/react-18.3.1/react.production.min.js",
        ).replace(
            "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
            "/static/vendor/react-18.3.1/react-dom.production.min.js",
        )
        asset_blob_anchor = (
            "        blobUrls[uuid] = URL.createObjectURL("
            "new Blob([finalBytes], { type: entry.mime }));"
        )
        asset_rewrite = """        if (entry.mime === 'text/javascript') {
          const localJs = new TextDecoder().decode(finalBytes)
            .split('https://unpkg.com/react@18.3.1/umd/react.production.min.js')
            .join('/static/vendor/react-18.3.1/react.production.min.js')
            .split('https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js')
            .join('/static/vendor/react-18.3.1/react-dom.production.min.js');
          finalBytes = new TextEncoder().encode(localJs);
        }
"""
        if asset_blob_anchor in content:
            content = content.replace(
                asset_blob_anchor,
                asset_rewrite + asset_blob_anchor,
                1,
            )
        back_link = (
            '<a href="/" aria-label="返回 ECOER Portal" '
            'style="position:fixed;right:16px;bottom:16px;z-index:2147483647;'
            'padding:10px 14px;border-radius:999px;background:#0f172a;color:#fff;'
            'font:600 14px/1.2 system-ui;text-decoration:none;box-shadow:0 8px 24px #0004">'
            '← 返回 ECOER Portal</a>'
        )
        document_swap_anchor = "    document.documentElement.replaceWith(doc.documentElement);"
        if document_swap_anchor in content:
            content = content.replace(
                document_swap_anchor,
                document_swap_anchor
                + "\n    document.body.insertAdjacentHTML('beforeend', "
                + json.dumps(back_link, ensure_ascii=False)
                + ");",
                1,
            )
        else:
            closing_tag = content.lower().rfind("</body>")
            if closing_tag < 0:
                closing_tag = content.lower().rfind("</html>")
            if closing_tag >= 0:
                content = content[:closing_tag] + back_link + content[closing_tag:]
            else:
                content += back_link
        dashboard_csp = (
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
            "style-src 'self' 'unsafe-inline' blob:; img-src 'self' data: blob:; "
            "font-src 'self' data: blob:; connect-src 'self' data: blob:; "
            "worker-src blob:; frame-ancestors 'none'"
        )
        self._send(
            handler,
            HTTPStatus.OK,
            content.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
            content_security_policy=dashboard_csp,
        )

    def _serve_static(self, handler: BaseHTTPRequestHandler, path: str) -> bool:
        names = {
            "/static/style.css": ("style.css", "text/css; charset=utf-8"),
            "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/static/vendor/react-18.3.1/react.production.min.js": (
                "vendor/react-18.3.1/react.production.min.js",
                "text/javascript; charset=utf-8",
            ),
            "/static/vendor/react-18.3.1/react-dom.production.min.js": (
                "vendor/react-18.3.1/react-dom.production.min.js",
                "text/javascript; charset=utf-8",
            ),
        }
        item = names.get(path)
        if not item:
            return False
        file_path = (self.static_dir / item[0]).resolve()
        if not file_path.is_relative_to(self.static_dir) or not file_path.is_file():
            self._send(handler, HTTPStatus.NOT_FOUND, b"Not found", content_type="text/plain")
            return True
        self._send(handler, HTTPStatus.OK, file_path.read_bytes(), content_type=item[1])
        return True

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if self._serve_static(handler, path):
            return
        if path == "/health":
            self._json(handler, HTTPStatus.OK, {"ok": True, "service": "ecoer-portal"})
            return
        if path == "/login":
            if self._session(handler):
                self._redirect(handler, "/")
            else:
                self._send(handler, HTTPStatus.OK, self._login_page())
            return
        if path == "/api/status":
            if not self._require_session(handler, api=True):
                return
            statuses = self.services.statuses()
            self._json(
                handler,
                HTTPStatus.OK,
                {
                    "projects": {
                        project_id: {
                            "state": status.state,
                            "detail": status.detail,
                            "owned": self.services.owns_process(project_id),
                        }
                        for project_id, status in statuses.items()
                    },
                    "tasks": self._api_tasks(),
                },
            )
            return
        session = self._require_session(handler)
        if not session:
            return
        if path == "/":
            task_id = query.get("task", [""])[-1]
            self._send(handler, HTTPStatus.OK, self._dashboard(session, task_id))
            return
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "download":
            self._serve_artifact(handler, parts[1])
            return
        if len(parts) == 2 and parts[0] == "projects":
            project = self.projects.get(parts[1])
            if project and project.kind == "cli":
                task_id = query.get("task", [""])[-1]
                self._send(
                    handler,
                    HTTPStatus.OK,
                    self._cli_project_page(session, project, task_id=task_id),
                )
                return
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "open":
            project = self.projects.get(parts[1])
            if project and project.kind == "file":
                self._serve_project_file(handler, project)
                return
        self._send(handler, HTTPStatus.NOT_FOUND, b"Not found", content_type="text/plain")

    def handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlparse(handler.path).path
        if path == "/projects/voc/run":
            session = self._require_session(handler)
            if session:
                self._run_voc_upload(handler, session)
            return
        try:
            form = self._form(handler)
        except (UnicodeDecodeError, ValueError):
            self._send(handler, HTTPStatus.BAD_REQUEST, b"Bad request", content_type="text/plain")
            return
        if path == "/login":
            result = self.sessions.login(form.get("username", ""), form.get("password", ""))
            if not result:
                self._send(
                    handler,
                    HTTPStatus.UNAUTHORIZED,
                    self._login_page("用户名或密码错误"),
                )
                return
            token, _session = result
            secure = "; Secure" if self.secure_cookie else ""
            cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax{secure}"
            self._send(handler, HTTPStatus.SEE_OTHER, headers={"Location": "/", "Set-Cookie": cookie})
            return
        session = self._require_session(handler)
        if not session:
            return
        if not self.sessions.csrf_valid(session, form.get("csrf_token", "")):
            self._send(handler, HTTPStatus.FORBIDDEN, b"Invalid CSRF token", content_type="text/plain")
            return
        if path == "/logout":
            self.sessions.logout(self._cookie_token(handler))
            cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            self._send(handler, HTTPStatus.SEE_OTHER, headers={"Location": "/login", "Set-Cookie": cookie})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "start":
            project_id = parts[1]
            if project_id not in self.projects:
                self._send(handler, HTTPStatus.NOT_FOUND, b"Unknown project", content_type="text/plain")
                return
            task_id = self.services.start(project_id)
            self._redirect(handler, f"/?task={task_id}")
            return
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "stop":
            project_id = parts[1]
            project = self.projects.get(project_id)
            if project is None or project.kind != "web":
                self._send(handler, HTTPStatus.NOT_FOUND, b"Unknown project", content_type="text/plain")
                return
            task_id = self.services.stop(project_id)
            self._redirect(handler, f"/?task={task_id}")
            return
        self._send(handler, HTTPStatus.NOT_FOUND, b"Not found", content_type="text/plain")


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "ECOERPortal/0.1"

    @property
    def application(self) -> PortalApplication:
        return self.server.application  # type: ignore[attr-defined,no-any-return]

    def do_GET(self) -> None:
        self.application.handle_get(self)

    def do_POST(self) -> None:
        self.application.handle_post(self)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[portal] {self.address_string()} {fmt % args}")


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: PortalApplication):
        self.application = application
        super().__init__(address, PortalHandler)


def make_server(application: PortalApplication, host: str, port: int) -> PortalServer:
    return PortalServer((host, port), application)


def run_server(application: PortalApplication, host: str, port: int) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("MVP only permits a loopback host")
    server = make_server(application, host, port)
    print(f"ECOER Portal running on http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nECOER Portal stopped")
    finally:
        server.server_close()
