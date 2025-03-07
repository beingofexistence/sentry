import {ColorChannels} from 'sentry/utils/profiling/flamegraph/flamegraphTheme';
import {Rect} from 'sentry/utils/profiling/speedscope';

import {colorComponentsToRGBA} from './colors/utils';
import {makeFormatter, makeTimelineFormatter} from './units/units';

interface Series {
  fillColor: string;
  lineColor: string;
  name: string;
  points: {x: number; y: number}[];
  type: 'line' | 'area';
}

export interface ProfileSeriesMeasurement extends Profiling.Measurement {
  name: string;
}

interface ChartOptions {
  type?: 'line' | 'area';
}

export class FlamegraphChart {
  configSpace: Rect;
  formatter: ReturnType<typeof makeFormatter>;
  tooltipFormatter: ReturnType<typeof makeFormatter>;
  timelineFormatter: (value: number) => string;
  series: Series[];
  domains: {
    x: [number, number];
    y: [number, number];
  } = {
    x: [0, 0],
    y: [0, 0],
  };

  static MIN_RENDERABLE_POINTS = 3;
  static Empty = new FlamegraphChart(Rect.Empty(), [], [[0, 0, 0, 0]]);

  constructor(
    configSpace: Rect,
    measurements: ProfileSeriesMeasurement[],
    colors: ColorChannels[],
    options: ChartOptions = {}
  ) {
    this.series = new Array<Series>();
    this.timelineFormatter = makeTimelineFormatter('nanoseconds');

    if (!measurements || !measurements.length) {
      this.formatter = makeFormatter('percent');
      this.tooltipFormatter = makeFormatter('percent');
      this.configSpace = configSpace.clone();
      return;
    }

    const type = options.type ? options.type : measurements.length > 1 ? 'line' : 'area';

    for (let j = 0; j < measurements.length; j++) {
      const measurement = measurements[j];
      this.series[j] = {
        type,
        name: measurement.name,
        lineColor: colorComponentsToRGBA(colors[j]),
        fillColor: colorComponentsToRGBA(colors[j]),
        points: new Array(measurement?.values?.length ?? 0).fill(0),
      };

      if (
        !measurement?.values?.length ||
        measurement?.values.length < FlamegraphChart.MIN_RENDERABLE_POINTS
      ) {
        continue;
      }

      for (let i = 0; i < measurement.values.length; i++) {
        const m = measurement.values[i];

        // Track and update Y max and min
        if (m.value > this.domains.y[1]) {
          this.domains.y[1] = m.value;
        }
        if (m.value < this.domains.y[0]) {
          this.domains.y[0] = m.value;
        }

        // Track and update X domain max and min
        if (m.elapsed_since_start_ns > this.domains.x[1]) {
          this.domains.x[1] = m.elapsed_since_start_ns;
        }
        if (m.elapsed_since_start_ns < this.domains.x[0]) {
          this.domains.x[1] = m.elapsed_since_start_ns;
        }

        this.series[j].points[i] = {x: m.elapsed_since_start_ns, y: m.value};
      }
    }

    this.series.sort((a, b) => {
      const aAvg = a.points.reduce((acc, point) => acc + point.y, 0) / a.points.length;
      const bAvg = b.points.reduce((acc, point) => acc + point.y, 0) / b.points.length;
      return bAvg - aAvg;
    });

    this.domains.y[1] = this.domains.y[1] + this.domains.y[1] * 0.1;
    this.configSpace = configSpace.withHeight(this.domains.y[1] - this.domains.y[0]);
    this.formatter = makeFormatter(measurements[0].unit, 0);
    this.tooltipFormatter = makeFormatter(measurements[0].unit, 2);
  }
}
