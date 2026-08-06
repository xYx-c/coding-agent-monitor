(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { useCallback, useEffect, useState } = SDK.hooks;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button, Input, Label, Select, SelectOption } = SDK.components;
  const h = React.createElement;
  const ROOT = "/api/plugins/coding-agent-monitor";

  function request(path, options) {
    const config = Object.assign({ headers: {} }, options || {});
    config.headers = Object.assign({ "Content-Type": "application/json" }, config.headers || {});
    return SDK.fetchJSON(ROOT + path, config);
  }

  function duration(iso) {
    if (!iso) return "—";
    const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
    if (seconds < 60) return seconds + "s";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m";
    return Math.floor(seconds / 3600) + "h " + Math.floor((seconds % 3600) / 60) + "m";
  }

  function apiError(error) {
    return error && (error.message || error.detail || String(error)) || "Request failed";
  }

  function RunCard(props) {
    const run = props.run;
    const manifest = run.manifest || {};
    const status = run.status || {};
    const [expanded, setExpanded] = useState(false);
    const [output, setOutput] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    const loadOutput = useCallback(function () {
      return request("/runs/" + encodeURIComponent(manifest.run_id) + "/output")
        .then(function (value) { setOutput(value.output || ""); })
        .catch(function (reason) { setError(apiError(reason)); });
    }, [manifest.run_id]);

    useEffect(function () {
      if (expanded) loadOutput();
    }, [expanded, loadOutput]);

    function refresh() {
      setBusy(true); setError("");
      request("/runs/" + encodeURIComponent(manifest.run_id) + "/refresh", { method: "POST", body: "{}" })
        .then(function () { return Promise.all([props.reload(), loadOutput()]); })
        .catch(function (reason) { setError(apiError(reason)); })
        .finally(function () { setBusy(false); });
    }

    function stop() {
      if (!window.confirm("Stop this coding-agent run? This only stops the isolated monitor tmux session.")) return;
      setBusy(true); setError("");
      request("/runs/" + encodeURIComponent(manifest.run_id) + "/stop", { method: "POST", body: "{}" })
        .then(props.reload)
        .catch(function (reason) { setError(apiError(reason)); })
        .finally(function () { setBusy(false); });
    }

    return h(Card, { className: "cam-card", key: manifest.run_id },
      h(CardHeader, { className: "cam-card-header" },
        h("div", null,
          h(CardTitle, { className: "cam-title" }, manifest.agent || "agent"),
          h("p", { className: "cam-summary" }, manifest.task_summary || "Task submitted"),
        ),
        h(Badge, { variant: "secondary", className: "cam-state" }, status.state || "unknown"),
      ),
      h(CardContent, { className: "cam-content" },
        h("dl", { className: "cam-metadata" },
          h("div", null, h("dt", null, "Phase"), h("dd", null, status.phase || "—")),
          h("div", null, h("dt", null, "Duration"), h("dd", null, duration(manifest.created_at))),
          h("div", null, h("dt", null, "Worktree"), h("dd", { title: manifest.workdir || "" }, manifest.workdir || "—")),
          h("div", null, h("dt", null, "Branch"), h("dd", null, manifest.git_branch || "—")),
        ),
        error ? h("p", { className: "cam-error", role: "alert" }, error) : null,
        h("div", { className: "cam-actions" },
          h(Button, { variant: "outline", size: "sm", disabled: busy, onClick: function () { setExpanded(!expanded); }, "aria-expanded": expanded }, expanded ? "Hide details" : "View details"),
          h(Button, { variant: "outline", size: "sm", disabled: busy, onClick: refresh, "aria-label": "Refresh run " + manifest.run_id }, "Refresh"),
          status.state !== "stopped" && status.state !== "completed" && status.state !== "failed"
            ? h(Button, { variant: "destructive", size: "sm", disabled: busy, onClick: stop, "aria-label": "Stop run " + manifest.run_id }, "Stop") : null,
        ),
        expanded ? h("section", { className: "cam-details", "aria-label": "Run details" },
          h("h3", null, "Read-only terminal"),
          h("pre", { className: "cam-terminal", tabIndex: 0, "aria-label": "Read-only agent terminal output" }, output || "No captured output yet."),
          h("h3", null, "Status metadata and recent events"),
          h("pre", { className: "cam-json" }, JSON.stringify({ status: status, manifest: manifest, recent_events: run.recent_events || [] }, null, 2)),
        ) : null,
      ),
    );
  }

  function StartForm(props) {
    const [agent, setAgent] = useState("claude");
    const [workdir, setWorkdir] = useState("");
    const [task, setTask] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    function submit(event) {
      event.preventDefault();
      if (!workdir.trim() || !task.trim()) { setError("Worktree and task are required."); return; }
      setBusy(true); setError("");
      request("/runs", { method: "POST", body: JSON.stringify({ agent: agent, workdir: workdir, task: task }) })
        .then(function () { setTask(""); return props.reload(); })
        .catch(function (reason) { setError(apiError(reason)); })
        .finally(function () { setBusy(false); });
    }

    return h(Card, { className: "cam-start" },
      h(CardHeader, null, h(CardTitle, null, "Start coding agent")),
      h(CardContent, null,
        h("form", { onSubmit: submit, className: "cam-form" },
          h("div", null,
            h(Label, { htmlFor: "cam-agent" }, "Agent"),
            h(Select, { id: "cam-agent", value: agent, onValueChange: setAgent, "aria-label": "Coding agent" },
              h(SelectOption, { value: "claude" }, "Claude Code"),
              h(SelectOption, { value: "codex" }, "Codex"),
            ),
          ),
          h("div", null,
            h(Label, { htmlFor: "cam-workdir" }, "Git worktree"),
            h(Input, { id: "cam-workdir", value: workdir, required: true, onChange: function (event) { setWorkdir(event.target.value); }, placeholder: "/path/to/repository" }),
          ),
          h("div", null,
            h(Label, { htmlFor: "cam-task" }, "Task"),
            h("textarea", { id: "cam-task", value: task, required: true, rows: 4, onChange: function (event) { setTask(event.target.value); }, placeholder: "Describe the coding task. It is transmitted only to the local supervisor.", className: "cam-textarea" }),
          ),
          error ? h("p", { className: "cam-error", role: "alert" }, error) : null,
          h(Button, { type: "submit", disabled: busy }, busy ? "Starting…" : "Start isolated run"),
        ),
      ),
    );
  }

  function CodingAgentsPage() {
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const reload = useCallback(function () {
      return request("/runs")
        .then(function (value) { setRuns(value.runs || []); setError(""); })
        .catch(function (reason) { setError(apiError(reason)); })
        .finally(function () { setLoading(false); });
    }, []);

    useEffect(function () {
      reload();
      const timer = window.setInterval(reload, 3000);
      return function () { window.clearInterval(timer); };
    }, [reload]);

    return h("div", { className: "cam-page" },
      h("header", { className: "cam-page-header" },
        h("div", null,
          h("h1", null, "Coding Agents"),
          h("p", null, "Local Claude/Codex runs. Only isolated monitor tmux sessions can be stopped here."),
        ),
        h(Button, { variant: "outline", onClick: reload, "aria-label": "Refresh coding agent list" }, "Refresh"),
      ),
      h(StartForm, { reload: reload }),
      error ? h("p", { className: "cam-error", role: "alert" }, error) : null,
      h("section", { className: "cam-runs", "aria-live": "polite", "aria-label": "Coding agent runs" },
        loading ? h("p", null, "Loading runs…") : null,
        !loading && runs.length === 0 ? h("p", { className: "cam-empty" }, "No coding-agent runs for this Hermes profile.") : null,
        runs.map(function (run) { return h(RunCard, { key: run.manifest && run.manifest.run_id, run: run, reload: reload }); }),
      ),
    );
  }

  window.__HERMES_PLUGINS__.register("coding-agent-monitor", CodingAgentsPage);
})();
