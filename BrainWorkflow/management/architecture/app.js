"use strict";

const list = document.getElementById("module-list");
const search = document.getElementById("module-search");
const detail = document.getElementById("module-detail");
const statusLine = document.getElementById("map-status");
let graph = null;
let modules = [];
let edges = [];
let selectedId = null;
let map = null;
let view = "workflow";

function switchView(nextView, requestedId) {
  view = nextView;
  modules = nextView === "workflow" ? map.workflow_steps : map.modules;
  edges = nextView === "workflow" ? map.workflow_edges : map.edges;
  document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
  document.querySelector('.module-rail label').textContent = view === "workflow" ? "Search workflow" : "Search modules";
  statusLine.textContent = `${modules.length} ${view === "workflow" ? "steps" : "modules"} · ${edges.length} ${view === "workflow" ? "transitions" : "dependencies"}`;
  if (graph) graph.destroy();
  graph = createGraph();
  renderList(search.value);
  selectModule(modules.some(item => item.id === requestedId) ? requestedId : modules[0].id);
}

function clearDetail(title) {
  detail.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = title;
  detail.append(heading);
}

function addText(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  detail.append(element);
  return element;
}

function addReferences(title, values) {
  if (!values || !values.length) return;
  addText("h3", title);
  const wrapper = document.createElement("div");
  wrapper.className = "reference-list";
  values.forEach(ref => {
    const item = document.createElement(ref.exists ? "a" : "span");
    item.textContent = ref.path + (ref.exists ? "" : " (planned)");
    if (ref.exists) item.href = "/workspace/" + ref.path.split("/").map(encodeURIComponent).join("/");
    wrapper.append(item);
  });
  detail.append(wrapper);
}

function selectModule(id) {
  const module = modules.find(item => item.id === id);
  if (!module) return;
  selectedId = id;
  clearDetail(module.name);
  addText("span", module.status, "status " + module.status);
  addText("p", module.purpose || module.responsibility);
  addText("h3", view === "workflow" ? "Workflow contract" : "Capabilities and limits");
  addText("p", module.detail);
  if (view === "workflow") {
    addText("p", "Runtime: " + (module.runtime_stages.join(", ") || "separate manual or knowledge operation"));
    addText("p", "Group: " + module.group);
    addText("h3", "Owning modules");
    module.owner_modules.forEach(owner => {
      const target = map.modules.find(item => item.id === owner);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency";
      button.textContent = target.name;
      button.addEventListener("click", () => switchView("modules", owner));
      detail.append(button);
    });
  } else {
    const steps = map.workflow_steps.filter(step => step.owner_modules.includes(id));
    if (steps.length) {
      addText("h3", "Workflow steps");
      steps.forEach(step => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "dependency";
        button.textContent = step.name;
        button.addEventListener("click", () => switchView("workflow", step.id));
        detail.append(button);
      });
    }
  }
  const related = edges.filter(item => item.from === id || item.to === id);
  if (related.length) {
    addText("h3", "Dependencies");
    related.forEach(edge => {
      const targetId = edge.from === id ? edge.to : edge.from;
      const target = modules.find(item => item.id === targetId);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency";
      button.textContent = `${edge.kind || edge.relation}: ${target.name} - ${edge.explanation}`;
      button.addEventListener("click", () => selectEdge(edge));
      detail.append(button);
    });
  }
  if (view === "modules") {
    addReferences("Code", module.code);
    addReferences("Tests", module.tests);
  }
  addReferences("Evidence", module.evidence);
  addReferences("Current tasks", [{path: "todo.md", exists: true}]);
  document.querySelectorAll(".module-button").forEach(button => button.classList.toggle("selected", button.dataset.node === id));
  if (graph) graph.nodes().forEach(node => node.toggleClass("selected", node.id() === id));
  if (graph && window.innerWidth < 620) {
    graph.zoom(0.95);
    graph.center(graph.$id(id));
  }
  history.replaceState(null, "", view === "workflow" ? `?view=workflow&step=${encodeURIComponent(id)}` : `?view=modules&module=${encodeURIComponent(id)}`);
}

function selectEdge(edge) {
  clearDetail(edge.kind || edge.relation);
  const from = modules.find(item => item.id === edge.from);
  const to = modules.find(item => item.id === edge.to);
  addText("p", `${from.name} to ${to.name}`);
  addText("p", edge.explanation);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "dependency";
  button.textContent = `Open ${to.name}`;
  button.addEventListener("click", () => selectModule(to.id));
  detail.append(button);
}

function renderList(query) {
  list.replaceChildren();
  const needle = query.trim().toLowerCase();
  modules.filter(item => `${item.name} ${item.purpose || item.responsibility} ${item.detail}`.toLowerCase().includes(needle)).forEach(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "module-button";
    button.dataset.node = item.id;
    if (view === "modules") button.dataset.module = item.id;
    const title = document.createElement("strong");
    title.textContent = item.name;
    const sub = document.createElement("small");
    sub.textContent = view === "workflow" ? `${item.group} / ${item.status}` : item.status;
    button.append(title, sub);
    button.addEventListener("click", () => selectModule(item.id));
    list.append(button);
  });
  if (graph) graph.nodes().forEach(node => node.toggleClass("dimmed", needle && !`${node.data("label")} ${node.data("description")}`.toLowerCase().includes(needle)));
}

function createGraph() {
  const research = modules.filter(item => item.group === "research");
  const positions = new Map(research.map((item, index) => [item.id, {x: 400, y: 90 + index * 72}]));
  positions.set("knowledge-refresh", {x: 100, y: 90});
  positions.set("knowledge-compile", {x: 100, y: 180});
  positions.set("final-submit", {x: 700, y: 90 + (research.length - 2) * 72});
  const instance = cytoscape({
      container: document.getElementById("architecture-graph"),
      elements: [
        ...modules.map(item => ({data: {id: item.id, label: item.name, description: item.purpose || item.responsibility, status: item.status, group: item.group || "module"}, position: positions.get(item.id)})),
        ...edges.map((item, index) => ({data: {id: `edge-${index}`, source: item.from, target: item.to, relation: item.kind || item.relation, explanation: item.explanation}}))
      ],
      layout: view === "workflow" ? {name: "preset", fit: true, padding: 50} : {name: "breadthfirst", directed: true, padding: 50, spacingFactor: 1.3},
      style: [
        {selector: "node", style: {"background-color": "#168d7e", "label": "data(label)", "color": "#203637", "font-size": 12, "font-weight": 600, "text-valign": "bottom", "text-margin-y": 7, "width": 28, "height": 28, "border-width": 2, "border-color": "#fff"}},
        {selector: 'node[status="partial"]', style: {"background-color": "#d79930"}},
        {selector: 'node[status="planned"]', style: {"background-color": "#7d9498"}},
        {selector: 'node[status="blocked"]', style: {"background-color": "#c35d55"}},
        {selector: 'node[status="manual"]', style: {"background-color": "#835da5"}},
        {selector: 'node[group="knowledge"]', style: {"shape": "round-rectangle"}},
        {selector: "node.selected", style: {"border-color": "#183d39", "border-width": 4, "width": 34, "height": 34}},
        {selector: ".dimmed", style: {opacity: 0.22}},
        {selector: "edge", style: {"width": 1.6, "line-color": "#93aaa7", "target-arrow-color": "#93aaa7", "target-arrow-shape": "triangle", "curve-style": "bezier"}},
        {selector: 'edge[relation="conditional"]', style: {"line-style": "dashed"}},
        {selector: 'edge[relation="manual"]', style: {"line-color": "#835da5", "target-arrow-color": "#835da5"}}
      ],
      minZoom: 0.25,
      maxZoom: 2.5
    });
  instance.on("tap", "node", event => selectModule(event.target.id()));
  instance.on("tap", "edge", event => selectEdge(edges[Number(event.target.id().split("-")[1])]));
  return instance;
}

async function loadMap() {
  try {
    const response = await fetch("/api/architecture", {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Map request failed: ${response.status}`);
    map = data;
    const params = new URLSearchParams(location.search);
    const initialView = params.get("view") === "modules" || (!params.has("view") && params.has("module")) ? "modules" : "workflow";
    switchView(initialView, initialView === "workflow" ? params.get("step") : params.get("module"));
    document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
    document.getElementById("fit-graph").addEventListener("click", () => graph.fit(undefined, 40));
    new ResizeObserver(() => {
      graph.resize();
      if (window.innerWidth < 620) {
        graph.zoom(0.95);
        graph.center(graph.$id(selectedId || modules[0].id));
      } else {
        graph.fit(undefined, 30);
      }
    }).observe(document.getElementById("architecture-graph"));
  } catch (error) {
    statusLine.textContent = "Map unavailable";
    clearDetail("Architecture map unavailable");
    addText("p", String(error), "error");
  }
}

search.addEventListener("input", () => renderList(search.value));
loadMap();
