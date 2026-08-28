import {useId, useMemo} from 'react';

type Props = {
  values: Array<number | null>;
  progress: number;
  stroke: string;
  completed: string;
  highlight: string;
  muted: string;
  /**
   * Fixed pixel height (sparklines). When omitted the chart stretches to fill
   * its flex container (elevation profile), so no vertical space is wasted.
   */
  height?: number;
  showArea?: boolean;
  smoothingSamples?: number;
  padX?: number;
  padY?: number;
};

const DEFAULT_PAD_X = 6;
const DEFAULT_PAD_Y = 6;
const DEFAULT_SMOOTHING_SAMPLES = 7;
const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 1000;

type Coordinate = {x: number; y: number};

const smoothValues = (
  raw: Array<number | null>,
  windowSize: number = DEFAULT_SMOOTHING_SAMPLES,
): Array<number | null> => {
  if (raw.length <= windowSize) return raw;
  const result: Array<number | null> = [];
  const half = Math.floor(windowSize / 2);
  for (let i = 0; i < raw.length; i++) {
    if (raw[i] === null || !Number.isFinite(raw[i])) {
      result.push(null);
      continue;
    }
    const start = Math.max(0, i - half);
    const end = Math.min(raw.length, i + half + 1);
    const window = raw.slice(start, end).filter((value): value is number => value !== null && Number.isFinite(value));
    result.push(window.reduce((sum, value) => sum + value, 0) / window.length);
  }
  return result;
};

const pathFor = (coordinates: Coordinate[]) =>
  coordinates.map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');

const splitSegments = (coordinates: Array<Coordinate | null>): Coordinate[][] => {
  const segments: Coordinate[][] = [];
  let current: Coordinate[] = [];
  for (const coordinate of coordinates) {
    if (coordinate) {
      current.push(coordinate);
    } else if (current.length > 0) {
      segments.push(current);
      current = [];
    }
  }
  if (current.length > 0) segments.push(current);
  return segments;
};

export const ProgressAxisChart = ({
  values,
  progress,
  stroke,
  completed,
  highlight,
  muted,
  height,
  showArea = true,
  smoothingSamples = DEFAULT_SMOOTHING_SAMPLES,
  padX = DEFAULT_PAD_X,
  padY = DEFAULT_PAD_Y,
}: Props) => {
  const gradientId = useId();

  const geometry = useMemo(() => {
    const stride = Math.max(1, Math.floor(values.length / 240));
    const sampled = values
      .map((value, index) => ({value, index}))
      .filter(({index}) => index % stride === 0 || index === values.length - 1);
    const valid = sampled
      .map(({value}) => value)
      .filter((value): value is number => value !== null && Number.isFinite(value));
    if (valid.length < 2) return null;

    const smoothed = smoothValues(sampled.map(({value}) => value), smoothingSamples);
    const smoothedValid = smoothed.filter((value): value is number => value !== null && Number.isFinite(value));
    const min = Math.min(...smoothedValid);
    const max = Math.max(...smoothedValid);
    const range = Math.max(max - min, 1e-4);

    const coordinates = smoothed.map((value, sampledIndex): Coordinate | null => {
      if (value === null || !Number.isFinite(value)) return null;
      return {
        x: (sampled[sampledIndex].index / Math.max(values.length - 1, 1)) * VIEW_WIDTH,
        y: VIEW_HEIGHT - ((value - min) / range) * VIEW_HEIGHT,
      };
    });
    const segments = splitSegments(coordinates).filter((segment) => segment.length >= 2);
    const coords = segments.flat();
    if (coords.length < 2) return null;

    return {coords, segments};
  }, [smoothingSamples, values]);

  const cursorX = Math.min(1, Math.max(0, progress)) * VIEW_WIDTH;
  const completedSegments = geometry
    ? geometry.segments.map((segment) => segment.filter(({x}) => x <= cursorX)).filter((segment) => segment.length >= 2)
    : [];
  const current = geometry
    ? geometry.coords.reduce(
        (nearest, coordinate) => (Math.abs(coordinate.x - cursorX) < Math.abs(nearest.x - cursorX) ? coordinate : nearest),
        geometry.coords[0],
      )
    : null;

  return (
    <div
      style={{
        width: '100%',
        height: height !== undefined ? height : undefined,
        flex: height !== undefined ? '0 0 auto' : '1 1 0',
        minWidth: 0,
        minHeight: 0,
        padding: `${padY}px ${padX}px`,
        boxSizing: 'border-box',
      }}
    >
      {geometry && current ? (
        <svg
          width="100%"
          height="100%"
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="none"
          style={{display: 'block', overflow: 'visible'}}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={completed} stopOpacity="0.28" />
              <stop offset="100%" stopColor={completed} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* Subtle baseline and midline grid */}
          <line x1={0} y1={VIEW_HEIGHT} x2={VIEW_WIDTH} y2={VIEW_HEIGHT} stroke={muted} strokeWidth="1" opacity="0.35" vectorEffect="non-scaling-stroke" />
          <line x1={0} y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} stroke={muted} strokeWidth="1" strokeDasharray="3 4" opacity="0.15" vectorEffect="non-scaling-stroke" />

          {/* Full track background */}
          {geometry.segments.map((segment, index) => (
            <path key={`track-${index}`} d={pathFor(segment)} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.3" vectorEffect="non-scaling-stroke" />
          ))}

          {/* Completed filled area */}
          {showArea
            ? completedSegments.map((segment, index) => {
                const path = pathFor(segment);
                const areaPath = `${path} L ${segment[segment.length - 1].x.toFixed(2)} ${VIEW_HEIGHT} L ${segment[0].x.toFixed(2)} ${VIEW_HEIGHT} Z`;
                return <path key={`area-${index}`} d={areaPath} fill={`url(#${gradientId})`} />;
              })
            : null}

          {/* Completed active line */}
          {completedSegments.map((segment, index) => (
            <path key={`completed-${index}`} d={pathFor(segment)} fill="none" stroke={completed} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          ))}

          {/* Current position indicator */}
          <line x1={cursorX} y1={current.y} x2={cursorX} y2={VIEW_HEIGHT} stroke={highlight} strokeWidth="1.2" opacity="0.75" vectorEffect="non-scaling-stroke" />
          <path d={`M ${cursorX} ${current.y} L ${cursorX} ${current.y}`} fill="none" stroke={highlight} strokeWidth="7" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
      ) : null}
    </div>
  );
};
