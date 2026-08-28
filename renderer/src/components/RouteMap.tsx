import {useMemo} from 'react';
import type {TelemetryPoint} from '../schema';
import type {Theme} from '../design/tokens';

type Props = {
  points: TelemetryPoint[];
  currentIndex: number;
  theme: Theme;
  topPadding?: number;
  bottomPadding?: number;
  sidePadding?: number;
  transparent?: boolean;
  showGrid?: boolean;
  showBackgroundRoute?: boolean;
  visualScale?: number;
};

const mercator = (lon: number, lat: number): [number, number] => {
  const safeLat = Math.max(-85, Math.min(85, lat));
  const x = (lon * Math.PI) / 180;
  const y = Math.log(Math.tan(Math.PI / 4 + (safeLat * Math.PI) / 360));
  return [x, y];
};

const routeGeometry = (points: TelemetryPoint[]) => {
  if (points.length === 0) return null;
  const projected = points.map((point) => mercator(point.lon, point.lat));
  const xs = projected.map(([x]) => x);
  const ys = projected.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dataW = Math.max(maxX - minX, 1e-9);
  const dataH = Math.max(maxY - minY, 1e-9);

  const coords = projected.map(([x, y]) => {
    return {x: x - minX, y: maxY - y};
  });
  const path = coords
    .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(9)} ${y.toFixed(9)}`)
    .join(' ');
  return {coords, path, dataW, dataH};
};

export const RouteMap = ({
  points,
  currentIndex,
  theme,
  topPadding = 48,
  bottomPadding = 48,
  sidePadding = 48,
  transparent = false,
  showGrid = true,
  showBackgroundRoute = true,
  visualScale = 1,
}: Props) => {
  // SVG's preserveAspectRatio performs the same uniform fit as the previous
  // pixel projection, but it is available synchronously on the first render.
  // Depending on ResizeObserver here caused occasional empty captures when a
  // Remotion worker took a screenshot between layout measurement and paint.
  const geometry = useMemo(() => routeGeometry(points), [points]);

  const safeIndex = geometry
    ? Math.min(geometry.coords.length - 1, Math.max(0, currentIndex))
    : 0;
  const current = geometry ? geometry.coords[safeIndex] : undefined;
  const completedPath = geometry
    ? geometry.coords
        .slice(0, safeIndex + 1)
        .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(9)} ${y.toFixed(9)}`)
        .join(' ')
    : '';

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        backgroundColor: transparent ? 'transparent' : theme.map,
        backgroundImage: showGrid
          ? `linear-gradient(${theme.grid} 1px, transparent 1px), linear-gradient(90deg, ${theme.grid} 1px, transparent 1px)`
          : 'none',
        backgroundSize: showGrid
          ? `${Math.round(64 * visualScale)}px ${Math.round(64 * visualScale)}px, ${Math.round(64 * visualScale)}px ${Math.round(64 * visualScale)}px`
          : undefined,
      }}
    >
      {geometry ? (
        <div
          style={{
            position: 'absolute',
            top: topPadding,
            right: sidePadding,
            bottom: bottomPadding,
            left: sidePadding,
          }}
        >
          <svg
            width="100%"
            height="100%"
            viewBox={`0 0 ${geometry.dataW} ${geometry.dataH}`}
            preserveAspectRatio="xMidYMid meet"
            style={{display: 'block', overflow: 'visible'}}
          >
            {showBackgroundRoute && (
              <path
                d={geometry.path}
                fill="none"
                stroke={theme.routeInactive}
                strokeWidth={4 * visualScale}
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            )}
            <path
              d={completedPath}
              fill="none"
              stroke={theme.route}
              strokeWidth={4.5 * visualScale}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            {current ? (
              <path
                d={`M ${current.x} ${current.y} L ${current.x} ${current.y}`}
                fill="none"
                stroke={theme.routeHighlight}
                strokeWidth={12 * visualScale}
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>
        </div>
      ) : null}
    </div>
  );
};
