import {useMemo} from 'react';
import type {TelemetryPoint} from '../schema';
import type {Theme} from '../design/tokens';
import {useElementSize} from '../lib/use-element-size';

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

const routeGeometry = (
  points: TelemetryPoint[],
  viewW: number,
  viewH: number,
  topPad: number,
  bottomPad: number,
  sidePad: number,
) => {
  const projected = points.map((point) => mercator(point.lon, point.lat));
  const xs = projected.map(([x]) => x);
  const ys = projected.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dataW = Math.max(maxX - minX, 1e-9);
  const dataH = Math.max(maxY - minY, 1e-9);

  const usableW = Math.max(viewW - 2 * sidePad, 10);
  const usableH = Math.max(viewH - topPad - bottomPad, 10);
  const scale = Math.min(usableW / dataW, usableH / dataH);

  const renderedW = dataW * scale;
  const renderedH = dataH * scale;

  const offsetX = sidePad + (usableW - renderedW) / 2;
  const offsetY = topPad + (usableH - renderedH) / 2;

  const coords = projected.map(([x, y]) => {
    const px = offsetX + (x - minX) * scale;
    const py = offsetY + (maxY - y) * scale;
    return {x: px, y: py};
  });
  const path = coords
    .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ');
  return {coords, path, viewW, viewH};
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
  // The map projects against its real layout box (1 SVG unit = 1 CSS pixel),
  // so it stays correctly registered in any container or aspect ratio.
  const [slotRef, slot] = useElementSize<HTMLDivElement>();
  const viewW = Math.round(slot.width);
  const viewH = Math.round(slot.height);

  const geometry = useMemo(() => {
    if (viewW < 2 || viewH < 2) return null;
    return routeGeometry(points, viewW, viewH, topPadding, bottomPadding, sidePadding);
  }, [bottomPadding, points, sidePadding, topPadding, viewH, viewW]);

  const safeIndex = geometry
    ? Math.min(geometry.coords.length - 1, Math.max(0, currentIndex))
    : 0;
  const current = geometry ? geometry.coords[safeIndex] : undefined;
  const completedPath = geometry
    ? geometry.coords
        .slice(0, safeIndex + 1)
        .map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
        .join(' ')
    : '';

  return (
    <div
      ref={slotRef}
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
        <svg
          width={viewW}
          height={viewH}
          viewBox={`0 0 ${viewW} ${viewH}`}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
          }}
        >
          {showBackgroundRoute && (
            <path
              d={geometry.path}
              fill="none"
              stroke={theme.routeInactive}
              strokeWidth={4 * visualScale}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          <path
            d={completedPath}
            fill="none"
            stroke={theme.route}
            strokeWidth={4.5 * visualScale}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {current ? (
            <circle
              cx={current.x}
              cy={current.y}
              r={6 * visualScale}
              fill={theme.routeHighlight}
            />
          ) : null}
        </svg>
      ) : null}
    </div>
  );
};
