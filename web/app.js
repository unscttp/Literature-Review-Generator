// The Literature Review Generator interface: new reviews, the run view with
// the workflow viewer, the paper library, the report and the activity log.
"use strict";

(() => {
  const t = (key, vars) => I18n.t(key, vars);
  const $ = (id) => document.getElementById(id);
  const ACTIVE = ["queued", "running"];
  const POLL_ACTIVE = 1500;
  const POLL_WAITING = 6000;

  const state = {
    info: null,
    overview: null, // workflow + skill graphs, for the start page
    runs: [],
    runId: null,
    summary: null,
    graph: null,
    library: null,
    report: null,
    tab: "workflow",
    filter: "all",
    selected: null, // "graphId/nodeId"
    openSkillGraph: null,
    timer: null,
  };

  // -- helpers ---------------------------------------------------------------

  function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  async function api(path, { method = "GET", body } = {}) {
    let response;
    try {
      response = await fetch(path, {
        method,
        headers: body !== undefined ? { "Content-Type": "application/json" } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      const failure = new Error(t("errors.network"));
      failure.code = "network";
      throw failure;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const failure = new Error(data.error || `${t("errors.generic")} (HTTP ${response.status})`);
      failure.code = data.code;
      throw failure;
    }
    return data;
  }

  function errorText(error) {
    return ["no_model", "no_key"].includes(error.code) ? t(`errors.${error.code}`) : error.message;
  }

  function formatDate(seconds) {
    if (!seconds) return "";
    return new Intl.DateTimeFormat(I18n.language, { dateStyle: "medium", timeStyle: "short" }).format(new Date(seconds * 1000));
  }

  function formatTime(iso) {
    return new Intl.DateTimeFormat(I18n.language, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(iso));
  }

  function badge(status) {
    return h("span", { class: `badge ${status}` }, t(`status.${status}`));
  }

  function stageName(id) {
    return I18n.has(`stages.${id}.name`) ? t(`stages.${id}.name`) : id;
  }

  function nodeName(graph, node) {
    if (!graph.parent && I18n.has(`stages.${node.id}.name`)) return t(`stages.${node.id}.name`);
    if (I18n.has(`graphNodes.${node.id}`)) return t(`graphNodes.${node.id}`);
    return node.name || node.id;
  }

  function nodeDescription(graph, node) {
    return !graph.parent && I18n.has(`stages.${node.id}.desc`) ? t(`stages.${node.id}.desc`) : "";
  }

  function graphTitle(id) {
    return I18n.has(`skills.graphs.${id}`) ? t(`skills.graphs.${id}`) : id;
  }

  // -- start page --------------------------------------------------------------

  function fillOptions() {
    const info = state.info;
    if (!info) return;
    document.querySelectorAll("select[data-options]").forEach((select) => {
      const name = select.dataset.options;
      const current = select.value || info.defaults[name];
      select.replaceChildren(...info.options[name].map((value) => h("option", { value }, t(`options.${name}.${value}`))));
      select.value = current;
    });
    const sources = $("source-options");
    const checked = new Set([...sources.querySelectorAll("input:checked")].map((input) => input.value));
    const initial = checked.size ? checked : new Set(info.defaults.sources);
    sources.replaceChildren(
      ...info.options.sources.map((value) =>
        h("label", {}, h("input", { type: "checkbox", name: "sources", value, checked: initial.has(value) }), t(`options.sources.${value}`)),
      ),
    );
    const design = document.querySelector("input[name=design_graphs]");
    if (!design.dataset.set) {
      design.checked = info.defaults.design_graphs !== false;
      design.dataset.set = "1";
    }
    const target = document.querySelector("input[name=target_papers]");
    if (!target.value) target.value = info.defaults.target_papers;
    renderBudget();
  }

  // -- the model -----------------------------------------------------------------
  // The service and model are chosen here; the list of models comes from the
  // service itself (with the saved key). Keys are sent to the local server once
  // and never come back: the server only says whether one is saved.

  const OTHER = "__other__";

  function serviceOf(id) {
    return state.models?.services.find((service) => service.id === id);
  }

  function serviceName(service) {
    return I18n.has(`services.${service.id}`) ? t(`services.${service.id}`) : service.label;
  }

  async function loadModels() {
    try {
      state.models = await api("/api/models");
    } catch (error) {
      state.models = null;
      setModelStatus(errorText(error), "error");
      return;
    }
    if (state.models.demo) { renderModelPicker(); return; }
    const current = state.models.current;
    const id = current && serviceOf(current.service) ? current.service : state.models.default_service;
    selectService(id, current && current.service === id ? current : null);
  }

  function selectService(id, saved) {
    const service = serviceOf(id);
    state.pick = {
      service: id,
      model: saved?.model || service.suggested_model || "",
      baseUrl: saved?.base_url || service.base_url || "",
      list: [],
      error: null,
      loading: false,
      other: false,
      changingKey: false,
      checked: null,
    };
    refreshModelList();
  }

  function modelChoice() {
    const pick = state.pick;
    const choice = { service: pick.service, model: pick.model.trim() };
    if (!serviceOf(pick.service).fixed_base_url) choice.base_url = pick.baseUrl.trim();
    return choice;
  }

  function modelReady() {
    if (state.models?.demo) return true;
    const pick = state.pick;
    const service = pick && serviceOf(pick.service);
    if (!service || !pick.model.trim()) return false;
    if (!service.fixed_base_url) return Boolean(pick.baseUrl.trim());
    return !service.needs_key || service.has_key;
  }

  function setModelStatus(text, kind) {
    const status = $("model-status");
    status.textContent = text || "";
    status.className = `small ${kind ? `status-${kind}` : "muted"}`;
  }

  async function refreshModelList() {
    const pick = state.pick;
    const service = serviceOf(pick.service);
    if (service.needs_key && service.fixed_base_url && !service.has_key) {
      Object.assign(pick, { list: [], error: "no_key", loading: false });
      renderModelPicker();
      return;
    }
    if (!service.fixed_base_url && !pick.baseUrl.trim()) {
      Object.assign(pick, { list: [], error: null, loading: false });
      renderModelPicker();
      return;
    }
    pick.loading = true;
    renderModelPicker();
    const body = { service: pick.service };
    if (!service.fixed_base_url) body.base_url = pick.baseUrl.trim();
    try {
      const reply = await api("/api/models/list", { method: "POST", body });
      if (state.pick !== pick) return; // another service was chosen meanwhile
      Object.assign(pick, { list: reply.models, error: reply.error, loading: false });
      // The service refused the key: offer to enter another one right away.
      if (/HTTP 40[13]/.test(reply.error || "")) pick.changingKey = true;
      if (!pick.model && reply.models.length) pick.model = reply.models[0];
      pick.other = Boolean(pick.model) && reply.models.length > 0 && !reply.models.includes(pick.model)
        && pick.model !== service.suggested_model;
    } catch (error) {
      Object.assign(pick, { list: [], error: errorText(error), loading: false });
    }
    renderModelPicker();
  }

  function renderModelPicker() {
    const demo = state.models?.demo;
    $("model-demo").hidden = !demo;
    $("model-controls").hidden = Boolean(demo);
    if (demo) {
      $("model-demo").textContent = t("model.demo");
      $("start-button").disabled = false;
      return;
    }
    const pick = state.pick;
    if (!pick) { $("start-button").disabled = true; return; }
    const service = serviceOf(pick.service);

    $("service-select").replaceChildren(
      ...state.models.services.map((s) => h("option", { value: s.id }, serviceName(s))),
    );
    $("service-select").value = pick.service;

    const ids = [...pick.list];
    if (service.suggested_model && !ids.includes(service.suggested_model) && !pick.list.length) {
      ids.unshift(service.suggested_model);
    }
    if (pick.model && !ids.includes(pick.model) && !pick.other) ids.unshift(pick.model);
    const options = ids.map((id) =>
      h("option", { value: id }, id === service.suggested_model ? `${id} ${t("model.suggested")}` : id));
    options.push(h("option", { value: OTHER }, t("model.other")));
    $("model-select").replaceChildren(...options);
    $("model-select").value = pick.other ? OTHER : pick.model || OTHER;
    $("model-select").disabled = pick.loading;
    $("refresh-models").disabled = pick.loading;
    const typing = pick.other || !pick.model;
    $("model-input-field").hidden = !typing;
    if (typing && document.activeElement !== $("model-input")) $("model-input").value = pick.model;

    $("base-url-field").hidden = service.fixed_base_url;
    if (document.activeElement !== $("base-url-input")) $("base-url-input").value = pick.baseUrl;

    $("key-field").hidden = !service.needs_key;
    const hint = I18n.has(`keyHints.${service.id}`) ? t(`keyHints.${service.id}`) : service.key_hint;
    $("key-label").textContent = `${t("model.key")} (${hint || serviceName(service)})`;
    const showEntry = !service.has_key || pick.changingKey;
    $("key-saved").hidden = showEntry;
    $("key-entry").hidden = !showEntry;
    $("key-note").textContent = t(service.fixed_base_url ? "model.keyNote" : "model.keyOptional", { service: serviceName(service) });

    if (pick.checked) {
      setModelStatus(pick.checked.ok ? t("model.works", { model: pick.checked.model }) : t("model.failed", { problem: pick.checked.problem }), pick.checked.ok ? "ok" : "error");
    } else if (pick.loading) {
      setModelStatus(t("model.loading"));
    } else if (pick.error === "no_key") {
      setModelStatus(t("model.needKey"));
    } else if (pick.error) {
      setModelStatus(t("model.listFailed", { error: pick.error }), "error");
    } else if (pick.list.length) {
      setModelStatus(t("model.count", { count: pick.list.length }));
    } else {
      setModelStatus("");
    }
    $("test-model").disabled = !modelReady() || pick.loading;
    $("start-button").disabled = !modelReady();
  }

  async function saveModelKey() {
    const pick = state.pick;
    const key = $("key-input").value.trim();
    if (!key) { $("key-input").focus(); return; }
    try {
      state.models = await api("/api/models/key", { method: "POST", body: { service: pick.service, api_key: key } });
      $("key-input").value = "";
      pick.changingKey = false;
      pick.checked = null;
      renderSettings();
      await refreshModelList();
    } catch (error) {
      setModelStatus(errorText(error), "error");
    }
  }

  async function testModel() {
    const pick = state.pick;
    const choice = modelChoice();
    $("test-model").disabled = true;
    setModelStatus(t("model.testing"));
    try {
      const reply = await api("/api/models/check", { method: "POST", body: choice });
      pick.checked = { ok: reply.ok, problem: reply.problem, model: choice.model };
    } catch (error) {
      pick.checked = { ok: false, problem: errorText(error), model: choice.model };
    }
    renderModelPicker();
  }

  function bindModelPicker() {
    $("service-select").addEventListener("change", (event) => {
      const current = state.models.current;
      const id = event.target.value;
      selectService(id, current && current.service === id ? current : null);
    });
    $("model-select").addEventListener("change", (event) => {
      const pick = state.pick;
      pick.checked = null;
      if (event.target.value === OTHER) {
        pick.other = true;
        pick.model = "";
        renderModelPicker();
        $("model-input").focus();
      } else {
        pick.other = false;
        pick.model = event.target.value;
        renderModelPicker();
      }
    });
    $("model-input").addEventListener("input", (event) => {
      state.pick.model = event.target.value;
      state.pick.checked = null;
      $("test-model").disabled = !modelReady();
      $("start-button").disabled = !modelReady();
    });
    $("base-url-input").addEventListener("change", (event) => {
      state.pick.baseUrl = event.target.value;
      state.pick.checked = null;
      refreshModelList();
    });
    $("refresh-models").addEventListener("click", refreshModelList);
    $("change-key").addEventListener("click", () => {
      state.pick.changingKey = true;
      renderModelPicker();
      $("key-input").focus();
    });
    $("save-model-key").addEventListener("click", saveModelKey);
    $("key-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); saveModelKey(); }
    });
    $("test-model").addEventListener("click", testModel);
  }

  /** The most model calls a review of this size may make (the stages' step limits). */
  function renderBudget() {
    const steps = state.info?.steps;
    const papers = Number(document.querySelector("input[name=target_papers]").value);
    if (!steps || !(papers >= 5 && papers <= 80)) {
      $("budget-note").textContent = "";
      return;
    }
    const calls = Object.entries(steps.base).reduce(
      (sum, [stage, base]) => sum + base + Math.ceil((steps.per_paper[stage] || 0) * papers),
      0,
    );
    $("budget-note").textContent = t("form.budget", { calls, graph: steps.skill_graph });
  }

  function renderOverview() {
    if (!state.overview) return;
    GraphViewer.render($("overview-graph"), state.overview.workflow, {
      t,
      nodeName,
      nodeDescription,
      legend: false,
      onSelect: (graph, node) => {
        state.selected = `${graph.id}/${node.id}`;
        renderOverview();
      },
      selected: state.selected,
    });
    if (state.selected && state.selected.startsWith(state.overview.workflow.graphs[0].id + "/")) {
      const id = state.selected.split("/")[1];
      $("overview-graph").appendChild(
        h("p", { class: "muted" }, h("strong", {}, `${stageName(id)}: `), t(`stages.${id}.desc`)),
      );
    }
    const list = $("skill-list");
    list.replaceChildren();
    for (const skill of state.overview.skills) {
      const card = h("div", { class: "skill" },
        h("h3", {}, t(`skills.${skill.name}.name`)),
        h("p", { class: "muted small" }, t(`skills.${skill.name}.description`)),
      );
      for (const graph of skill.graphs) {
        const open = state.openSkillGraph === graph.id;
        const name = graph.bundled ? graphTitle(graph.id) : graph.title;
        card.append(
          h("p", { class: "graph-name" }, graph.bundled ? "◇ " : "◆ ", name,
            graph.bundled ? null : h("span", { class: "badge saved" }, t("graphs.savedBadge")),
            graph.runs ? h("span", { class: "muted small" }, ` · ${t("graphs.runs", { count: graph.runs })}`) : null),
          graph.bundled ? null : h("button", {
            class: "ghost danger",
            onclick: async () => {
              if (!confirm(t("graphs.confirmRemove", { title: graph.title }))) return;
              try {
                state.overview = await api(`/api/skills/${skill.name}/graphs/${graph.id}`, { method: "DELETE" });
                renderOverview();
              } catch (error) { alert(errorText(error)); }
            },
          }, t("graphs.remove")),
          h("button", {
            class: "ghost",
            "aria-expanded": String(open),
            onclick: () => { state.openSkillGraph = open ? null : graph.id; renderOverview(); },
          }, open ? t("skills.hide") : t("skills.show")),
        );
      }
      list.appendChild(card);
      for (const graph of skill.graphs) {
        if (state.openSkillGraph !== graph.id) continue;
        const area = h("div", { class: "card skill-graph" },
          h("h3", {}, `${t("viewer.skillGraph")}: ${graph.bundled ? graphTitle(graph.id) : graph.title}`),
          h("p", { class: "muted small" }, graph.explanation),
        );
        const holder = h("div", { class: "graph-area" });
        area.appendChild(holder);
        list.appendChild(area);
        GraphViewer.render(holder, { graphs: [{ ...graph, parent: null, depth: 0, id: graph.id }] }, {
          t, nodeName: (g, node) => (I18n.has(`graphNodes.${node.id}`) ? t(`graphNodes.${node.id}`) : node.name),
          nodeDescription: (g, node) => [allowanceText(node.allowance), node.instruction].filter(Boolean).join("\n"),
          nodeSubtitle: (g, node) => allowanceText(node.allowance),
          legend: false, numbered: false,
        });
      }
    }
  }

  async function submitNew(event) {
    event.preventDefault();
    const form = $("new-form");
    const data = new FormData(form);
    const number = (name) => (data.get(name) ? Number(data.get(name)) : null);
    const body = {
      topic: (data.get("topic") || "").trim(),
      language: data.get("language"),
      style: data.get("style"),
      review_type: data.get("review_type"),
      target_papers: number("target_papers"),
      from_year: number("from_year"),
      to_year: number("to_year"),
      sources: data.getAll("sources"),
      notes: (data.get("notes") || "").trim(),
    };
    body.design_graphs = data.get("design_graphs") === "on";
    if (!state.models?.demo) body.model = modelChoice();
    const error = $("form-error");
    error.hidden = true;
    const button = $("start-button");
    button.disabled = true;
    button.textContent = t("form.starting");
    try {
      const run = await api("/api/runs", { method: "POST", body });
      form.querySelector("[name=topic]").value = "";
      form.querySelector("[name=notes]").value = "";
      state.models = await api("/api/models"); // the choice is now the default
      await loadRuns();
      location.hash = `#run/${run.id}`;
    } catch (failure) {
      error.textContent = errorText(failure);
      error.hidden = false;
    } finally {
      button.textContent = t("form.start");
      renderModelPicker();
    }
  }

  // -- the run list --------------------------------------------------------------

  async function loadRuns() {
    try {
      state.runs = (await api("/api/runs")).runs;
    } catch (error) {
      state.runs = state.runs || [];
    }
    renderRuns();
  }

  function renderRuns() {
    const list = $("run-list");
    list.replaceChildren(
      ...state.runs.map((run) =>
        h("li", {},
          h("button", {
            "aria-current": String(run.id === state.runId),
            onclick: () => { location.hash = `#run/${run.id}`; closeMenu(); },
          },
          h("span", { class: "run-name" }, run.title),
          h("span", { class: "run-sub" }, badge(run.status), formatDate(run.created))),
        ),
      ),
    );
    $("no-runs").hidden = state.runs.length > 0;
  }

  // -- one run --------------------------------------------------------------------

  function schedule() {
    clearTimeout(state.timer);
    const status = state.summary?.status;
    if (!state.runId) return;
    const delay = ACTIVE.includes(status) ? POLL_ACTIVE : status === "waiting" ? POLL_WAITING : null;
    if (delay) state.timer = setTimeout(refreshRun, delay);
  }

  async function refreshRun() {
    const runId = state.runId;
    if (!runId) return;
    try {
      const [summary, graph] = await Promise.all([api(`/api/runs/${runId}`), api(`/api/runs/${runId}/graph`)]);
      if (runId !== state.runId) return;
      const statusChanged = state.summary && state.summary.status !== summary.status;
      state.summary = summary;
      state.graph = graph;
      if (state.tab === "library") state.library = await api(`/api/runs/${runId}/library`);
      if (state.tab === "report") state.report = await api(`/api/runs/${runId}/report`);
      renderRun();
      if (statusChanged) loadRuns();
    } catch (error) {
      if (error.code === "not_found") { location.hash = "#new"; return; }
      $("run-error").textContent = errorText(error);
      $("run-error").hidden = false;
    }
    schedule();
  }

  function renderRun() {
    const summary = state.summary;
    if (!summary) return;
    $("run-title").textContent = summary.title;
    const stats = summary.stats || {};
    const meta = [
      `${t("run.model")}: ${summary.model || "—"}`,
      `${t("run.created")}: ${formatDate(summary.created)}`,
      `${summary.counts.total} ${t("run.papers")} · ${summary.counts.included} ${t("run.included")}`,
    ];
    if (stats.decisions) meta.push(`${stats.decisions} ${t("run.decisions")} · ${stats.tool_calls} ${t("run.toolCalls")}`);
    if (stats.tokens) meta.push(`${stats.tokens.toLocaleString(I18n.language)} ${t("run.tokens")}`);
    if (stats.retries) meta.push(`${stats.retries} ${t("run.retries")}`);
    $("run-meta").textContent = meta.join(" · ");
    $("run-status").className = `badge ${summary.status}`;
    $("run-status").textContent = t(`status.${summary.status}`);
    $("cancel-button").hidden = ![...ACTIVE, "waiting"].includes(summary.status);
    $("resume-button").hidden = !["interrupted", "failed", "cancelled"].includes(summary.status);
    $("delete-button").hidden = ACTIVE.includes(summary.status);
    const error = $("run-error");
    error.hidden = !summary.error || !["failed", "interrupted"].includes(summary.status);
    error.textContent = summary.error ? `${t("run.error")}: ${summary.error}` : "";
    renderApprovals();
    document.querySelectorAll(".tabs [data-tab]").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === state.tab));
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.dataset.panel !== state.tab; });
    if (state.tab === "workflow") renderGraph();
    if (state.tab === "library") renderLibrary();
    if (state.tab === "report") renderReport();
    if (state.tab === "activity") renderActivity();
  }

  function list(items) {
    return h("ul", {}, (items || []).map((item) => h("li", {}, item)));
  }

  function renderApprovals() {
    const box = $("approvals");
    const approvals = state.summary.status === "waiting" ? state.summary.approvals : [];
    if (box.dataset.shown === approvals.map((a) => a.id).join(",") && approvals.length) return; // keep a comment being typed
    box.dataset.shown = approvals.map((a) => a.id).join(",");
    box.replaceChildren();
    for (const approval of approvals) {
      const card = h("div", { class: "card approval" });
      if (approval.kind === "scope_review" && approval.scope) {
        const scope = approval.scope;
        const years = [scope.from_year, scope.to_year].filter(Boolean).join(" – ");
        card.append(
          h("h2", {}, t("approval.heading")),
          h("p", { class: "muted" }, t("approval.intro")),
          h("dl", {},
            h("dt", {}, t("approval.title")), h("dd", {}, scope.title),
            h("dt", {}, t("approval.questions")), h("dd", {}, list(scope.research_questions)),
            h("dt", {}, t("approval.inclusion")), h("dd", {}, list(scope.inclusion_criteria)),
            scope.exclusion_criteria?.length ? [h("dt", {}, t("approval.exclusion")), h("dd", {}, list(scope.exclusion_criteria))] : null,
            h("dt", {}, t("approval.queries")), h("dd", {}, list(scope.search_queries)),
            years ? [h("dt", {}, t("approval.years")), h("dd", {}, years)] : null,
            scope.notes ? [h("dt", {}, t("approval.notes")), h("dd", {}, scope.notes)] : null,
          ),
        );
      } else if (approval.kind === "graph_creation" || approval.kind === "skill_graph_save") {
        card.append(...graphReview(approval));
      } else {
        card.append(h("h2", {}, t("approval.other")), h("pre", {}, JSON.stringify(approval.details, null, 2)));
      }
      const comment = h("textarea", { rows: 2, placeholder: t("approval.commentPlaceholder"), "aria-label": t("approval.requestChanges") });
      const note = h("p", { class: "notice error", hidden: true });
      const decide = async (approved) => {
        if (!approved && approval.kind === "scope_review" && !comment.value.trim()) {
          note.textContent = t("approval.commentNeeded");
          note.hidden = false;
          comment.focus();
          return;
        }
        card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
        try {
          state.summary = await api(`/api/runs/${state.runId}/approvals/${approval.id}`, {
            method: "POST",
            body: { approved, comment: comment.value.trim() },
          });
          box.dataset.shown = "";
          renderRun();
          schedule();
          loadRuns();
        } catch (error) {
          note.textContent = errorText(error);
          note.hidden = false;
          card.querySelectorAll("button").forEach((button) => { button.disabled = false; });
        }
      };
      const labels = {
        scope_review: ["approval.approve", "approval.requestChanges"],
        graph_creation: ["graphs.approve", "graphs.reject"],
        skill_graph_save: ["graphs.save", "graphs.dontSave"],
      }[approval.kind] || ["approval.approveOther", "approval.rejectOther"];
      if (approval.kind === "graph_creation") comment.placeholder = t("graphs.commentPlaceholder");
      if (approval.can_revise && approval.kind !== "skill_graph_save") card.append(comment);
      card.append(note, h("div", { class: "actions" },
        h("button", { class: "primary", onclick: () => decide(true) }, t(labels[0])),
        h("button", { class: approval.can_revise ? "" : "danger", onclick: () => decide(false) }, t(labels[1])),
      ));
      box.appendChild(card);
    }
  }

  function allowanceText(id) {
    return I18n.has(`allowances.${id}`) ? t(`allowances.${id}`) : id || "—";
  }

  /** A graph's nodes drawn with the viewer, then each step: what it may do and its instruction. */
  function graphPreview(graph, start) {
    const holder = h("div", { class: "graph-area" });
    const nodes = graph.nodes.map((node) => ({
      id: node.id, name: node.name || node.id, allowance: node.allowance, status: "pending",
    }));
    GraphViewer.render(holder, { graphs: [{ id: "preview", title: "", parent: null, depth: 0, start, nodes, edges: graph.edges }] }, {
      t,
      nodeName: (g, node) => node.name,
      nodeDescription: (g, node) => allowanceText(node.allowance),
      nodeSubtitle: (g, node) => allowanceText(node.allowance),
      legend: false,
      numbered: false,
    });
    const steps = h("ol", { class: "graph-steps" }, graph.nodes.map((node) =>
      h("li", {},
        h("strong", {}, node.name || node.id),
        h("span", { class: "muted small" }, ` — ${allowanceText(node.allowance)}`),
        (node.config || {}).instruction ? h("p", { class: "small" }, node.config.instruction) : null,
      )));
    return [holder, h("details", {}, h("summary", {}, t("graphs.steps")), steps)];
  }

  function graphReview(approval) {
    const details = approval.details || {};
    const stage = stageName(approval.node);
    const skill = details.skill?.name;
    const skillName = skill ? t(`skills.${skill}.name`) : "";
    const saved = details.skill_graph;
    const title = saved ? (I18n.has(`skills.graphs.${saved}`) ? t(`skills.graphs.${saved}`) : approval.skill_graph_title || saved) : "";
    const parts = [];
    if (approval.kind === "skill_graph_save") {
      parts.push(
        h("h2", {}, t("graphs.saveTitle", { skill: skillName })),
        h("p", { class: "muted" }, t("graphs.saveIntro")),
      );
    } else if (saved) {
      parts.push(
        h("h2", {}, t("graphs.runSavedTitle", { title })),
        h("p", { class: "muted" }, t("graphs.runSavedIntro", { stage, skill: skillName })),
      );
    } else {
      parts.push(
        h("h2", {}, t("graphs.designedTitle", { stage })),
        h("p", { class: "muted" }, t("graphs.designedIntro")),
      );
    }
    parts.push(h("p", {}, h("strong", {}, `${t("graphs.explanation")}: `), details.explanation || ""));
    parts.push(...graphPreview(details.graph || { nodes: [], edges: [] }, details.start || []));
    if (details.usage_scenario && !saved) {
      const scenario = h("div", { class: "scenario" });
      scenario.innerHTML = Markdown.render(details.usage_scenario); // escaped by the renderer
      parts.push(h("details", { open: approval.kind === "skill_graph_save" },
        h("summary", {}, t("graphs.scenario", { skill: skillName })), scenario));
    }
    return parts;
  }

  function renderGraph() {
    if (!state.graph) return;
    GraphViewer.render($("run-graph"), state.graph, {
      t,
      nodeName,
      nodeDescription,
      selected: state.selected,
      caption: (graph) => {
        if (!graph.parent) return null;
        const savedNote = graph.saved === "saved"
          ? ` · ${t("graphs.savedInto", { skill: t(`skills.${graph.skill}.name`) })}`
          : "";
        if (graph.designed) {
          return [
            h("strong", {}, t("graphs.designedCaption")),
            ` — ${t("viewer.runBy")} ${stageName(graph.parent.node)} · `,
            t(`status.${graph.status}`) !== `status.${graph.status}` ? t(`status.${graph.status}`) : graph.status,
            savedNote,
          ];
        }
        const title = I18n.has(`skills.graphs.${graph.title}`) ? t(`skills.graphs.${graph.title}`) : graph.skill_graph_title || graph.title;
        return [
          h("strong", {}, `${t("viewer.skillGraph")}: ${title}`),
          ` — ${t("viewer.runBy")} ${stageName(graph.parent.node)} · `,
          t(`status.${graph.status}`) !== `status.${graph.status}` ? t(`status.${graph.status}`) : graph.status,
        ];
      },
      onSelect: (graph, node) => {
        state.selected = `${graph.id}/${node.id}`;
        renderGraph();
      },
    });
    renderStageDetail();
  }

  function renderStageDetail() {
    const box = $("stage-detail");
    if (!state.selected || !state.graph) { box.hidden = true; return; }
    const [graphId, nodeId] = state.selected.split("/");
    const graph = state.graph.graphs.find((g) => g.id === graphId);
    const node = graph?.nodes.find((n) => n.id === nodeId);
    if (!node) { box.hidden = true; return; }
    const output = graph.parent ? null : state.summary?.stages?.[nodeId];
    box.replaceChildren(...[
      h("h3", {}, nodeName(graph, node), " ", badge(node.status)),
      nodeDescription(graph, node) ? h("p", { class: "muted" }, nodeDescription(graph, node)) : null,
      h("p", { class: "small muted" },
        `${node.attempts || 0} ${t("viewer.attempts")} · ${node.decisions || 0} ${t("viewer.decisions")} · ${node.tool_calls || 0} ${t("viewer.toolCalls")}`,
        node.tokens ? ` · ${node.tokens.toLocaleString(I18n.language)} ${t("run.tokens")}` : "",
        node.allowance ? ` · ${t("viewer.allowance")}: ${node.allowance}` : ""),
      node.error ? h("p", { class: "notice error" }, node.error) : null,
      graph.parent ? null : h("h3", {}, t("viewer.stageOutput")),
      graph.parent ? null : h("div", { class: "output" }, output || t("viewer.noOutput")),
      h("button", { class: "ghost", onclick: () => { state.selected = null; renderGraph(); } }, t("viewer.close")),
    ].filter(Boolean));
    box.hidden = false;
  }

  function renderLibrary() {
    const library = state.library;
    const filters = $("library-filters");
    const table = $("library-table");
    if (!library) { table.replaceChildren(); return; }
    const counts = { all: library.counts.total, ...library.counts };
    filters.replaceChildren(
      ...["all", "included", "candidate", "excluded"].map((key) =>
        h("button", {
          "aria-pressed": String(state.filter === key),
          onclick: () => { state.filter = key; renderLibrary(); },
        }, `${t(`library.filter.${key}`)} (${counts[key] || 0})`),
      ),
    );
    const papers = library.papers.filter((paper) => state.filter === "all" || paper.status === state.filter);
    $("library-empty").hidden = papers.length > 0;
    table.replaceChildren(
      h("thead", {}, h("tr", {},
        h("th", {}, t("library.id")), h("th", {}, t("library.paper")), h("th", {}, t("library.year")),
        h("th", {}, t("library.status")), h("th", {}, t("library.themes")))),
      h("tbody", {}, papers.map((paper) => {
        const authors = (paper.authors || []).slice(0, 4).join(", ") + ((paper.authors || []).length > 4 ? " …" : "");
        const link = paper.doi ? `https://doi.org/${paper.doi}` : paper.url;
        const notes = paper.notes ? Object.entries(paper.notes) : [];
        return h("tr", {},
          h("td", {}, paper.id),
          h("td", {},
            h("div", { class: "title" }, link && /^https?:/.test(link) ? h("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, paper.title) : paper.title),
            h("div", { class: "authors" }, [authors, paper.venue].filter(Boolean).join(" — "),
              paper.cited_by != null ? ` · ${t("library.cited")} ${paper.cited_by}` : ""),
            paper.reason ? h("div", { class: "reason" }, `${t("library.reason")}: ${paper.reason}`) : null,
            notes.length ? h("details", {}, h("summary", {}, t("library.notes")),
              h("dl", {}, notes.map(([key, value]) => [h("dt", {}, I18n.has(`library.fields.${key}`) ? t(`library.fields.${key}`) : key), h("dd", {}, value)]))) : null,
          ),
          h("td", {}, paper.year || ""),
          h("td", { class: `status-${paper.status}` }, t(`library.statuses.${paper.status}`)),
          h("td", {}, (paper.themes || []).join("; ")),
        );
      })),
    );
    $("search-list").replaceChildren(
      ...library.searches.map((search) =>
        h("li", {}, `${search.source}: “${search.query}” — ${search.found} ${t("library.found")}, ${search.new} ${t("library.new")}`)),
    );
  }

  function renderReport() {
    const report = state.report;
    const body = $("report-body");
    const hasText = report && state.summary.sections.length > 0;
    $("download-md").href = `/api/runs/${state.runId}/report.md`;
    $("download-bib").href = `/api/runs/${state.runId}/references.bib`;
    document.querySelector(".report-tools").hidden = !hasText;
    if (!hasText) {
      body.replaceChildren(h("p", { class: "muted" }, t("report.empty")));
      $("report-check").replaceChildren();
      return;
    }
    $("report-stats").textContent = `${report.words.toLocaleString(I18n.language)} ${t("report.words")} · ${report.cited.length} ${t("report.cited")}`;
    const check = report.check;
    const checkBox = $("report-check");
    const draft = state.summary.status !== "completed";
    if (check.ok) {
      checkBox.replaceChildren(h("p", { class: "notice check" }, t("report.checkOk")));
    } else {
      // Blocking issues keep the review stage from finishing; the rest are warnings.
      const item = (issue) => h("li", {},
        t(`report.issues.${issue.kind}`),
        issue.section ? ` (${issue.section})` : "",
        issue.ids ? `: ${issue.ids.join(", ")}` : "",
        issue.sections ? `: ${issue.sections.join(", ")}` : "",
      );
      const blocking = check.issues.filter((issue) => issue.blocking);
      const warnings = check.issues.filter((issue) => !issue.blocking);
      checkBox.replaceChildren(h("div", { class: blocking.length && !draft ? "notice error check" : "notice warning check" },
        draft ? h("p", {}, t("report.draftNote")) : null,
        blocking.length ? [h("strong", {}, t("report.blockingHeading")), h("ul", {}, blocking.map(item))] : null,
        warnings.length ? [h("strong", {}, t("report.warningsHeading")), h("ul", {}, warnings.map(item))] : null,
      ));
    }
    body.innerHTML = Markdown.render(report.markdown); // escaped by the renderer
  }

  function renderActivity() {
    const items = state.summary.activity || [];
    $("activity-list").replaceChildren(
      ...(items.length ? items.slice().reverse() : []).map((entry) =>
        h("li", { class: entry.kind.endsWith("failed") ? "failed" : "" },
          h("span", { class: "time" }, formatTime(entry.at)),
          h("span", { class: "node" }, entry.node ? stageName(entry.node) : "—"),
          h("span", { class: "what" },
            h("strong", {}, t(`activity.kinds.${entry.kind}`)),
            entry.tool ? ` ${entry.tool}` : "",
            entry.text ? ` ${entry.text}` : ""),
        )),
    );
    if (!items.length) $("activity-list").replaceChildren(h("li", { class: "muted" }, t("activity.empty")));
  }

  async function runAction(action) {
    try {
      if (action === "delete") {
        if (!confirm(t("run.confirmDelete"))) return;
        await api(`/api/runs/${state.runId}`, { method: "DELETE" });
        await loadRuns();
        location.hash = "#new";
        return;
      }
      state.summary = await api(`/api/runs/${state.runId}/${action}`, { method: "POST", body: {} });
      renderRun();
      schedule();
      loadRuns();
    } catch (error) {
      $("run-error").textContent = errorText(error);
      $("run-error").hidden = false;
    }
  }

  // -- settings ----------------------------------------------------------------

  function renderSettings() {
    const services = (state.models?.services || []).filter((service) => service.needs_key);
    $("key-list").replaceChildren(
      ...services.map((service) =>
        h("li", {},
          h("span", {}, serviceName(service), " — ",
            h("span", { class: service.has_key ? "key-ok" : "muted" }, service.has_key ? t("settings.keySaved") : t("settings.noKey"))),
          service.has_key
            ? h("button", { type: "button", class: "ghost", onclick: () => removeModelKey(service.id) }, t("settings.removeKey"))
            : null,
        )),
    );
    $("openalex-state").textContent = state.info?.openalex_key ? t("settings.keySet") : t("settings.keyNotSet");
    $("remove-key").hidden = !state.info?.openalex_key;
  }

  async function removeModelKey(id) {
    try {
      state.models = await api("/api/models/key", { method: "POST", body: { service: id, api_key: "" } });
      renderSettings();
      if (state.pick?.service === id) selectService(id, state.models.current);
    } catch (error) {
      $("openalex-state").textContent = errorText(error);
    }
  }

  async function saveKey(value) {
    try {
      const result = await api("/api/settings", { method: "POST", body: { openalex_api_key: value } });
      state.info.openalex_key = result.openalex_key;
      $("openalex-key").value = "";
      $("settings-saved").hidden = false;
      renderSettings();
    } catch (error) {
      $("openalex-state").textContent = errorText(error);
    }
  }

  // -- routing -----------------------------------------------------------------

  function route() {
    const match = /^#run\/([0-9A-Za-z-]+)$/.exec(location.hash);
    clearTimeout(state.timer);
    if (match) {
      if (state.runId !== match[1]) {
        Object.assign(state, { runId: match[1], summary: null, graph: null, library: null, report: null, selected: null, tab: "workflow" });
        $("approvals").dataset.shown = "";
      }
      $("new-view").hidden = true;
      $("run-view").hidden = false;
      $("run-error").hidden = true;
      refreshRun();
    } else {
      state.runId = null;
      state.selected = null;
      $("new-view").hidden = false;
      $("run-view").hidden = true;
      renderOverview();
      // Reviews may have saved graphs into the skills since the page was loaded.
      api("/api/workflow").then((view) => { state.overview = view; renderOverview(); }).catch(() => {});
    }
    renderRuns();
  }

  function closeMenu() {
    $("sidebar").classList.remove("open");
    $("menu-button").setAttribute("aria-expanded", "false");
  }

  async function start() {
    await I18n.init();
    $("new-form").addEventListener("submit", submitNew);
    bindModelPicker();
    document.querySelector("input[name=target_papers]").addEventListener("input", renderBudget);
    $("new-button").addEventListener("click", () => { location.hash = "#new"; closeMenu(); });
    $("language-button").addEventListener("click", () => I18n.use(I18n.other()));
    $("menu-button").addEventListener("click", () => {
      const open = $("sidebar").classList.toggle("open");
      $("menu-button").setAttribute("aria-expanded", String(open));
    });
    $("settings-button").addEventListener("click", () => {
      $("settings-saved").hidden = true;
      renderSettings();
      $("settings-dialog").showModal();
    });
    $("save-key").addEventListener("click", () => saveKey($("openalex-key").value.trim()));
    $("remove-key").addEventListener("click", () => saveKey(""));
    $("cancel-button").addEventListener("click", () => runAction("cancel"));
    $("resume-button").addEventListener("click", () => runAction("resume"));
    $("delete-button").addEventListener("click", () => runAction("delete"));
    $("copy-report").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(state.report?.markdown || "");
        $("copy-report").textContent = t("report.copied");
        setTimeout(() => { $("copy-report").textContent = t("report.copy"); }, 1500);
      } catch (error) { /* clipboard not available */ }
    });
    document.querySelectorAll(".tabs [data-tab]").forEach((tab) => {
      tab.addEventListener("click", async () => {
        state.tab = tab.dataset.tab;
        renderRun();
        await refreshRun();
      });
    });
    document.addEventListener("languagechange", () => {
      fillOptions();
      renderModelPicker();
      renderSettings();
      renderOverview();
      renderRuns();
      $("approvals").dataset.shown = "";
      if (state.summary) renderRun();
    });
    window.addEventListener("hashchange", route);
    let resized;
    window.addEventListener("resize", () => {
      clearTimeout(resized);
      resized = setTimeout(() => (state.runId ? renderGraph() : renderOverview()), 150);
    });
    try {
      [state.info, state.overview] = await Promise.all([api("/api/info"), api("/api/workflow")]);
    } catch (error) {
      $("form-error").textContent = errorText(error);
      $("form-error").hidden = false;
    }
    fillOptions();
    await Promise.all([loadModels(), loadRuns()]);
    route();
  }

  start();
})();
