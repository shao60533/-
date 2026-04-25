/**
 * ECharts tree-shaking bundle.
 * Import `echarts` from this module to get only what we use.
 */
import * as echarts from "echarts/core"
import { LineChart, BarChart, PieChart, ScatterChart, CandlestickChart } from "echarts/charts"
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
  ToolboxComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([
  LineChart, BarChart, PieChart, ScatterChart, CandlestickChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkPointComponent, MarkLineComponent,
  MarkAreaComponent, VisualMapComponent, ToolboxComponent,
  CanvasRenderer,
])

export { echarts }
export type { EChartsOption } from "echarts"
