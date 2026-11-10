/*! ECharts 6.1.0 | Apache-2.0 | custom OpenAver Insights bundle */
import { init, use } from 'echarts/core';
import { BarChart, PieChart, TreemapChart } from 'echarts/charts';
import {
    AxisPointerComponent,
    GraphicComponent,
    GridComponent,
    MarkLineComponent,
    TooltipComponent,
} from 'echarts/components';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';

use([
    BarChart,
    PieChart,
    TreemapChart,
    AxisPointerComponent,
    GraphicComponent,
    GridComponent,
    MarkLineComponent,
    TooltipComponent,
    LabelLayout,
    UniversalTransition,
    CanvasRenderer,
]);

window.echarts = { init };
