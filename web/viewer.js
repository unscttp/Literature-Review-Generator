// The workflow viewer: draws a run's graphs as SVG with each node's status.
//
// The first graph is the review's eight stages. A skill graph that a stage
// ran appears below it as its own graph, indented and captioned with the
// stage that ran it. Nodes are laid out in layers (longest path from the
// start), wrapped into rows that snake left-right-left, so the eight stages
// fit on a laptop screen and on a phone.
"use strict";

window.GraphViewer = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  const NODE_W = 168;
  const NODE_H = 64;
  const GAP_X = 44;
  const GAP_Y = 22;
  const ROW_GAP = 46;
  const PAD = 10;

  function el(name, attributes = {}, text) {
    const node = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function layers(graph) {
    const incoming = {};
    graph.nodes.forEach((node) => { incoming[node.id] = []; });
    graph.edges.forEach((edge) => { if (incoming[edge.to]) incoming[edge.to].push(edge.from); });
    const depth = {};
    const visit = (id, seen = new Set()) => {
      if (id in depth) return depth[id];
      if (seen.has(id)) return 0; // a cycle: should not happen
      seen.add(id);
      const parents = incoming[id] || [];
      depth[id] = parents.length ? Math.max(...parents.map((parent) => visit(parent, seen) + 1)) : 0;
      return depth[id];
    };
    graph.nodes.forEach((node) => visit(node.id));
    const result = [];
    graph.nodes.forEach((node) => { (result[depth[node.id]] = result[depth[node.id]] || []).push(node); });
    return result.filter(Boolean);
  }

  function layout(graph, maxColumns) {
    const columns = layers(graph);
    const perRow = Math.max(1, Math.min(maxColumns, columns.length));
    const rows = Math.ceil(columns.length / perRow);
    const tallest = Math.max(...columns.map((column) => column.length));
    const bandHeight = tallest * NODE_H + (tallest - 1) * GAP_Y;
    const positions = {};
    columns.forEach((column, index) => {
      const row = Math.floor(index / perRow);
      let slot = index % perRow;
      if (row % 2 === 1) slot = perRow - 1 - slot; // snake: odd rows run right to left
      const x = PAD + slot * (NODE_W + GAP_X);
      const columnHeight = column.length * NODE_H + (column.length - 1) * GAP_Y;
      const top = PAD + row * (bandHeight + ROW_GAP) + (bandHeight - columnHeight) / 2;
      column.forEach((node, k) => { positions[node.id] = { x, y: top + k * (NODE_H + GAP_Y), row }; });
    });
    return {
      positions,
      width: PAD * 2 + perRow * NODE_W + (perRow - 1) * GAP_X,
      height: PAD * 2 + rows * bandHeight + (rows - 1) * ROW_GAP,
    };
  }

  function edgePath(a, b) {
    if (a.row === b.row) {
      const leftToRight = b.x > a.x;
      const x1 = leftToRight ? a.x + NODE_W : a.x;
      const x2 = leftToRight ? b.x : b.x + NODE_W;
      const y1 = a.y + NODE_H / 2;
      const y2 = b.y + NODE_H / 2;
      const mid = (x1 + x2) / 2;
      return { d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, end: [x2, y2], dir: leftToRight ? 0 : 180 };
    }
    const x1 = a.x + NODE_W / 2;
    const y1 = a.y + NODE_H;
    const x2 = b.x + NODE_W / 2;
    const y2 = b.y;
    const mid = (y1 + y2) / 2;
    return { d: `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`, end: [x2, y2], dir: 90 };
  }

  function arrow([x, y], degrees, done) {
    const r = (degrees * Math.PI) / 180;
    const back = (angle) => [x - 8 * Math.cos(r + angle), y - 8 * Math.sin(r + angle)];
    const [p1, p2] = [back(0.45), back(-0.45)];
    return el("path", { d: `M${x},${y} L${p1[0]},${p1[1]} L${p2[0]},${p2[1]} Z`, class: done ? "arrow done" : "arrow" });
  }

  function clip(text, limit) {
    const chars = Array.from(text || "");
    // CJK characters are about twice as wide as Latin ones.
    let width = 0;
    let out = "";
    for (const char of chars) {
      width += /[　-鿿＀-￯]/.test(char) ? 2 : 1;
      if (width > limit) return out + "…";
      out += char;
    }
    return out;
  }

  function nodeSubtitle(node, t) {
    if (node.activity) {
      const kind = node.activity.kind;
      if (kind === "tool" && node.activity.tool) return clip(node.activity.tool, 26);
      return t(`viewer.activity.${kind}`);
    }
    if (node.status === "pending") return "";
    const parts = [t(`status.${node.status}`) !== `status.${node.status}` ? t(`status.${node.status}`) : node.status];
    if (node.tool_calls) parts.push(`${node.tool_calls} ⚙`);
    return parts.join(" · ");
  }

  function drawGraph(graph, options) {
    const { positions, width, height } = layout(graph, options.columns);
    const svg = el("svg", {
      class: "graph",
      viewBox: `0 0 ${width} ${height}`,
      width,
      height,
      role: "group",
      "aria-label": options.label || graph.title,
    });
    const status = Object.fromEntries(graph.nodes.map((node) => [node.id, node.status]));
    graph.edges.forEach((edge) => {
      const a = positions[edge.from];
      const b = positions[edge.to];
      if (!a || !b) return;
      const done = status[edge.from] === "completed" && status[edge.to] !== "pending";
      const path = edgePath(a, b);
      svg.appendChild(el("path", { d: path.d, class: done ? "edge done" : "edge" }));
      svg.appendChild(arrow(path.end, path.dir, done));
    });
    graph.nodes.forEach((node, index) => {
      const p = positions[node.id];
      const classes = ["node", node.status];
      if (options.selected === `${graph.id}/${node.id}`) classes.push("selected");
      if (options.withChildren && options.withChildren.has(node.id)) classes.push("has-child");
      const group = el("g", { class: classes.join(" "), transform: `translate(${p.x},${p.y})`, tabindex: "0", role: "button" });
      const name = options.nodeName(graph, node);
      group.appendChild(el("title", {}, [name, options.nodeDescription(graph, node)].filter(Boolean).join("\n")));
      group.appendChild(el("rect", { width: NODE_W, height: NODE_H, rx: 9 }));
      if (options.numbered) group.appendChild(el("text", { x: 12, y: 21, class: "number" }, String(index + 1)));
      group.appendChild(el("text", { x: options.numbered ? 28 : 12, y: 22, class: "title" }, clip(name, options.numbered ? 17 : 19)));
      const subtitle = options.nodeSubtitle ? options.nodeSubtitle(graph, node) : nodeSubtitle(node, options.t);
      group.appendChild(el("text", { x: 12, y: 46, class: "sub" }, clip(subtitle, 27)));
      group.appendChild(el("circle", { cx: NODE_W - 13, cy: 15, r: 5, class: "status-dot" }));
      const select = () => options.onSelect && options.onSelect(graph, node);
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
      });
      svg.appendChild(group);
    });
    return svg;
  }

  function legend(t) {
    const box = document.createElement("div");
    box.className = "legend";
    for (const key of ["pending", "running", "waiting", "completed", "failed"]) {
      const item = document.createElement("span");
      item.className = key;
      item.textContent = key === "pending" ? t("status.idle") : t(`status.${key}`);
      box.appendChild(item);
    }
    return box;
  }

  /**
   * Render a graph view ({graphs: [...]}) into container.
   * options: t, nodeName(graph, node), nodeDescription(graph, node), caption(graph),
   * onSelect(graph, node), selected ("graphId/nodeId").
   */
  function render(container, view, options) {
    const narrow = (container.clientWidth || window.innerWidth) < 560;
    const columns = narrow ? 2 : 4;
    container.replaceChildren();
    const parents = new Map();
    (view.graphs || []).forEach((graph) => {
      if (graph.parent) {
        if (!parents.has(graph.parent.graph)) parents.set(graph.parent.graph, new Set());
        parents.get(graph.parent.graph).add(graph.parent.node);
      }
    });
    (view.graphs || []).forEach((graph, index) => {
      const block = document.createElement("div");
      block.className = graph.parent ? "graph-block child" : "graph-block";
      if (graph.depth > 1) block.style.marginLeft = `${18 * graph.depth}px`;
      const caption = options.caption && options.caption(graph);
      if (caption) {
        const p = document.createElement("p");
        p.className = "graph-caption";
        p.append(...caption);
        block.appendChild(p);
      }
      block.appendChild(
        drawGraph(graph, {
          ...options,
          columns,
          numbered: index === 0 && !graph.parent && options.numbered !== false,
          withChildren: parents.get(graph.id),
          label: graph.title,
        }),
      );
      container.appendChild(block);
    });
    if (options.legend !== false) container.appendChild(legend(options.t));
  }

  return { render, layout };
})();
