// Draws a chart from the server's checked description. The model never supplies a specification.
window.mdoChart = (function () {
  const INK = "#17191c", MUTED = "#5f6670", GRID = "#e3e3de";
  // Fixed order, from the dashboard's palette. A series keeps its colour by its place in the sorted names.
  const CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#a32424", "#e5a50a", "#475467", "#8a4fbf", "#0f8b9d"];
  const ACCENT = "#c40000";
  const MARK = { line: 2, point: 64 };
  let regions = null;

  function axisConfig() {
    return {
      font: "'Segoe UI', Roboto, Arial, sans-serif",
      axis: { labelColor: MUTED, titleColor: MUTED, gridColor: GRID, domainColor: GRID, tickColor: GRID, labelFontSize: 11, titleFontSize: 11 },
      legend: { labelColor: INK, titleColor: MUTED, orient: "top" },
      view: { stroke: null },
    };
  }
  const label = (f) => f.replace(/_/g, " ").replace("per 100k", "per 100,000").replace("cfr pct", "case fatality (%)");

  function spec(pub) {
    const c = pub.chart;
    const base = { $schema: "https://vega.github.io/schema/vega-lite/v6.json", width: "container", height: c.type === "heatmap" ? 340 : 300,
      data: { values: pub.rows }, config: axisConfig() };
    const num = (f) => ({ field: f, type: "quantitative", title: label(f) });
    const nominal = (f) => ({ field: f, type: "nominal", title: null });
    const ordered = (f) => ({ field: f, type: "ordinal", title: label(f), sort: "ascending" });
    const colour = c.series ? { field: c.series, type: "nominal", title: null, scale: { range: CATEGORICAL } } : { value: ACCENT };
    const tip = pub.columns.map((f) => ({ field: f, title: label(f) }));

    if (c.type === "map") return mapSpec(pub, base);
    if (c.type === "line") {
      const periods = new Set(pub.rows.map((r) => r[c.x])).size;
      // Weeks read as a continuous axis, years as whole steps.
      const x = c.x === "week" ? { ...num("week"), scale: { nice: false, zero: false }, axis: { format: "d", tickMinStep: 1 } } : { ...ordered(c.x), axis: { labelAngle: 0 } };
      const enc = { x, y: num(c.y), color: colour, tooltip: tip };
      const layers = [{ mark: { type: "line", strokeWidth: MARK.line, interpolate: "monotone" }, encoding: enc }];
      layers.push({ mark: { type: "point", filled: true, size: periods <= 16 ? MARK.point : 120, opacity: periods <= 16 ? 1 : 0 }, encoding: enc });
      return { ...base, layer: layers };
    }
    if (c.type === "bar") {
      const yNumeric = pub.rows.some((r) => typeof r[c.y] === "number");
      const mark = { type: "bar", cornerRadiusEnd: 4 };
      const enc = yNumeric
        ? { y: { ...nominal(c.x), sort: c.x_time ? "ascending" : "-x" }, x: num(c.y) }
        : { y: { ...nominal(c.y), sort: "-x" }, x: num(c.x) };
      if (yNumeric && c.x_time) { enc.x = { ...ordered(c.x), axis: { labelAngle: 0 } }; enc.y = num(c.y); }
      enc.color = colour;
      if (c.series) enc[yNumeric && c.x_time ? "xOffset" : "yOffset"] = { field: c.series };
      return { ...base, height: yNumeric && c.x_time ? 300 : { step: 20 }, mark, encoding: { ...enc, tooltip: tip } };
    }
    if (c.type === "scatter") {
      return { ...base, mark: { type: "point", size: 80, filled: true, color: ACCENT }, encoding: { x: num(c.x), y: num(c.y), tooltip: tip } };
    }
    const axis = (f, time) => (time ? ordered(f) : nominal(f));
    return { ...base, mark: { type: "rect" }, encoding: { x: { ...axis(c.x, c.x_time), axis: { labelAngle: 0, labelOverlap: true } }, y: axis(c.y, c.y_time),
      color: { field: c.series, type: "quantitative", title: label(c.series), scale: { scheme: "reds" } }, tooltip: tip } };
  }

  function mapSpec(pub, base) {
    const c = pub.chart;
    return { ...base, height: 360, data: { values: regions, format: { type: "json", property: "features" } },
      transform: [{ lookup: "properties.region", from: { data: { values: pub.rows }, key: c.x, fields: [c.y] } }],
      projection: { type: "equirectangular" },
      mark: { type: "geoshape", stroke: "#ffffff", strokeWidth: 2 },
      encoding: { color: { field: c.y, type: "quantitative", title: label(c.y), scale: { scheme: "reds" } },
        tooltip: [{ field: "properties.region", title: "Region" }, { field: c.y, title: label(c.y) }] } };
  }

  async function draw(container, pub) {
    if (!pub.chart || !window.vegaEmbed) return false;
    if (pub.chart.type === "map" && !regions) {
      const res = await fetch("/api/regions");
      if (!res.ok) throw new Error("no map");
      regions = await res.json();
    }
    await window.vegaEmbed(container, spec(pub), { actions: false, renderer: "svg", ast: true, expr: window.vegaInterpreter && window.vegaInterpreter.expressionInterpreter });
    return true;
  }
  return { draw, spec };
})();
