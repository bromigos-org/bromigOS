// One trend: a single series over time, drawn by ECharts in the world's own colour (one hue, so
// no legend: the heading names it). A crosshair and a tooltip read each point; the same
// readings are in a table for screen readers. The tooltip is drawn on the canvas (richText),
// so the chart writes no inline style into the page, and nothing moves under reduced motion.
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { AxisPointerComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { clock, when } from "@/lib/time";

echarts.use([LineChart, GridComponent, TooltipComponent, AxisPointerComponent, CanvasRenderer]);

const tok = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#39ff14";
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function Trend({ name, unit, points, max, now }: { name: string; unit: string; points: [number, number | null][]; max?: number; now: number }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    const draw = () => {
      const pri = tok("--phosphor"), muted = tok("--static"), rule = tok("--guard"), text = tok("--text"), panel = tok("--panel");
      chart.setOption(
        {
          animation: !reduced(),
          grid: { left: 40, right: 12, top: 12, bottom: 24 },
          xAxis: {
            type: "time",
            axisLine: { lineStyle: { color: rule } },
            axisTick: { show: false },
            axisLabel: { color: muted, fontFamily: "Geist Mono, monospace", fontSize: 11, formatter: (v: number) => clock(v) },
            splitLine: { show: false },
          },
          yAxis: {
            type: "value",
            min: 0,
            max: max ?? undefined,
            splitNumber: 2,
            axisLabel: { color: muted, fontFamily: "Geist Mono, monospace", fontSize: 11 },
            splitLine: { lineStyle: { color: rule, width: 1 } },
          },
          tooltip: {
            trigger: "axis",
            renderMode: "richText",
            backgroundColor: panel,
            borderColor: pri,
            textStyle: { color: text, fontFamily: "Geist Mono, monospace", fontSize: 12 },
            axisPointer: { type: "line", lineStyle: { color: muted, width: 1 } },
            valueFormatter: (v: unknown) => (v === null || v === undefined ? "no reading" : `${v} ${unit}`),
          },
          series: [
            {
              type: "line",
              name,
              data: points,
              showSymbol: false,
              connectNulls: false,
              lineStyle: { color: pri, width: 2 },
              itemStyle: { color: pri },
              areaStyle: { color: pri, opacity: 0.08 },
              emphasis: { disabled: true },
            },
          ],
        },
        true,
      );
    };
    draw();
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    const mo = new MutationObserver(draw); // the world changed: new tokens
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-world"] });
    return () => {
      ro.disconnect();
      mo.disconnect();
      chart.dispose();
    };
  }, [name, unit, points, max]);
  const vals = points.filter((p) => p[1] !== null) as [number, number][];
  const last = vals[vals.length - 1];
  const lo = vals.length ? Math.min(...vals.map((p) => p[1])) : null;
  const hi = vals.length ? Math.max(...vals.map((p) => p[1])) : null;
  return (
    <figure className="trend-fig">
      <div
        className="trend"
        ref={el}
        role="img"
        aria-label={vals.length ? `${name}: from ${lo} to ${hi} ${unit}; ${last[1]} ${unit} at ${clock(last[0])}` : `${name}: no readings`}
        title={`${name} over time. Hover the chart for each reading.`}
      />
      <table className="sr-only">
        <caption>{name}</caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">{unit}</th>
          </tr>
        </thead>
        <tbody>
          {points.map(([t, v]) => (
            <tr key={t}>
              <td>{when(t, now)}</td>
              <td>{v ?? "no reading"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
