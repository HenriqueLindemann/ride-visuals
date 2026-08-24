import {useMemo} from 'react';
import type {TelemetryPoint} from '../schema';
import type {Theme} from '../design/tokens';

type Props = {
  points: TelemetryPoint[];
  currentIndex: number;
  theme: Theme;
  transparent?: boolean;
  showGrid?: boolean;
};

const mercator = (lon: number, lat: number): [number, number] => {
  const safeLat = Math.max(-85, Math.min(85, lat));
  const x = (lon * Math.PI) / 180;
  const y = Math.log(Math.tan(Math.PI / 4 + (safeLat * Math.PI) / 360));
  return [x, y];
};

const routeGeometry = (points: TelemetryPoint[]) => {
  const projected = points.map((point) => mercator(point.lon, point.lat));
  const xs = projected.map(([x]) => x);
  const ys = projected.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dataW = Math.max(maxX - minX, 1e-9);
  const dataH = Math.max(maxY - minY, 1e-9);
  const scale = Math.min(880 / dataW, 880 / dataH);
  const offsetX = (1000 - dataW * scale) / 2;
  const offsetY = (1000 - dataH * scale) / 2;
  const coords = projected.map(([x, y]) => {
    const px = offsetX + (x - minX) * scale;
    const py = 1000 - (offsetY + (y - minY) * scale);
    return {x: px, y: py};
  });
  const path = coords
    .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ');
  return {coords, path};
};

export const RouteMap = ({points, currentIndex, theme, transparent = false, showGrid = true}: Props) => {
  const geometry = useMemo(() => routeGeometry(points), [points]);
  const safeIndex = Math.min(
    geometry.coords.length - 1,
    Math.max(0, currentIndex),
  );
  const current = geometry.coords[safeIndex];
  const completedPath = geometry.coords
    .slice(0, safeIndex + 1)
    .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ');
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
        backgroundSize: showGrid ? '64px 64px, 64px 64px' : undefined,
      }}
    >
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet" style={{position: 'absolute', inset: '5%', width: '90%', height: '90%'}}>
        <path d={geometry.path} fill="none" stroke={theme.routeInactive} strokeWidth="4" strokeLinecap="square" strokeLinejoin="miter" />
        <path
          d={completedPath}
          fill="none"
          stroke={theme.route}
          strokeWidth="4.2"
          strokeLinecap="square"
          strokeLinejoin="miter"
        />
        {current ? <rect x={current.x - 5} y={current.y - 5} width="10" height="10" fill={theme.routeHighlight} /> : null}
      </svg>
    </div>
  );
};
