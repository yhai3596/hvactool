(() => {
  const labels = {
    online: "在线", offline: "未启动", ready: "可用", launching: "启动中",
    disabled: "已禁用", misconfigured: "配置异常", occupied: "端口占用", error: "异常",
    "not-applicable": "无需检测"
  };

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = value == null ? "" : String(value);
    return node.innerHTML;
  }

  function renderTasks(tasks) {
    const target = document.getElementById("task-rows");
    if (!target) return;
    const projectFilter = target.dataset.projectFilter;
    if (projectFilter) tasks = tasks.filter(task => task.project_id === projectFilter);
    if (!tasks.length) {
      target.innerHTML = '<tr><td colspan="5" class="empty">还没有启动记录</td></tr>';
      return;
    }
    target.innerHTML = tasks.map(task => `<tr>
      <td>${escapeHtml(task.project_name || task.project_id)}</td><td>${escapeHtml(task.action)}</td>
      <td><span class="task-status">${escapeHtml(task.status)}</span>${task.has_artifact && task.status === "completed" ? ` <a class="task-download" href="/tasks/${encodeURIComponent(task.id)}/download">下载结果</a>` : ""}</td>
      <td>${escapeHtml(task.message)}</td><td>${escapeHtml(task.created_at)}</td>
    </tr>`).join("");
  }

  async function refresh() {
    if (!document.querySelector(".dashboard")) return;
    try {
      const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
      if (response.status === 401) { location.href = "/login"; return; }
      if (!response.ok) return;
      const data = await response.json();
      Object.entries(data.projects).forEach(([id, status]) => {
        const card = document.querySelector(`[data-project-id="${CSS.escape(id)}"]`);
        if (!card) return;
        const badge = card.querySelector("[data-status]");
        const detail = card.querySelector("[data-status-detail]");
        badge.textContent = labels[status.state] || status.state;
        badge.className = `badge badge-${status.state}`;
        detail.textContent = status.detail;
        const startButton = card.querySelector("[data-start-button]");
        if (startButton) {
          const locked = ["online", "launching", "occupied", "disabled", "misconfigured"].includes(status.state);
          startButton.disabled = locked;
          startButton.textContent = status.state === "online" ? "已在线" :
            status.state === "launching" ? "启动中…" :
            status.state === "occupied" ? "端口占用" : "启动服务";
        }
        const openLink = card.querySelector("[data-open-link]");
        if (openLink) openLink.classList.toggle("disabled", status.state !== "online");
        const stopForm = card.querySelector("[data-stop-form]");
        const stopButton = card.querySelector("[data-stop-button]");
        const canStop = ["online", "launching", "occupied"].includes(status.state);
        if (stopForm) stopForm.hidden = !canStop;
        if (stopButton) {
          stopButton.disabled = !canStop;
          stopButton.textContent = "停止服务";
        }
      });
      renderTasks(data.tasks || []);
    } catch (_) {
      // Central refresh is best-effort; keep the last known state visible.
    }
  }

  if (document.querySelector(".dashboard")) {
    document.querySelectorAll("[data-start-form]").forEach(form => {
      form.addEventListener("submit", () => {
        const button = form.querySelector("[data-start-button]");
        if (button) { button.disabled = true; button.textContent = "提交中…"; }
      });
    });
    document.querySelectorAll("[data-stop-form]").forEach(form => {
      form.addEventListener("submit", () => {
        const button = form.querySelector("[data-stop-button]");
        if (button) { button.disabled = true; button.textContent = "停止中…"; }
      });
    });
    window.setInterval(refresh, 2000);
  }
})();
