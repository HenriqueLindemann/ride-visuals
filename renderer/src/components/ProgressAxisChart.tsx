import {useMemo} from 'react';

type Props = {
  values: Array<number | null>;
  progress: number;
  stroke: string;
  completed: string;
  highlight: string;
  muted: string;
  height?: number;
};

const WIDTH = 300;
const PAD = 5;

type Coordinate = {x: number; y: number};

const pathFor = (coordinates: Coordinate[]) =>
  coordinates.map(({x, y}, index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');

export const ProgressAxisChart = ({values, progress, stroke, completed, highlight, muted, height = 180}: Props) => {
  const geometry = useMemo(() => {
    const stride = Math.max(1, Math.floor(values.length / 360));
    const sampled = values.filter((_, index) => index % stride === 0 || index === values.length - 1);
    const valid = sampled.filter((value): value is number => value !== null);
    if (valid.length < 2) return null;
    const min = Math.min(...valid);
    const max = Math.max(...valid);
    const range = Math.max(max - min, 1);
    const coords = sampled.map((value, index) => {
      if (value === null) return null;
      return {
        x: PAD + (index / Math.max(sampled.length - 1, 1)) * (WIDTH - PAD * 2),
        y: height - PAD - ((value - min) / range) * (height - PAD * 2),
      };
    });
    const validCoords = coords.filter((value): value is Coordinate => value !== null);
    return {validCoords, path: pathFor(validCoords)};
  }, [height, values]);
  if (!geometry) return null;
  const {validCoords, path} = geometry;
  const cursorX = PAD + Math.min(1, Math.max(0, progress)) * (WIDTH - PAD * 2);
  const completedCoords = validCoords.filter(({x}) => x <= cursorX);
  const completedPath = pathFor(completedCoords);
  const current = validCoords.reduce(
    (nearest, coordinate) => Math.abs(coordinate.x - cursorX) < Math.abs(nearest.x - cursorX) ? coordinate : nearest,
    validCoords[0],
  );

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} preserveAspectRatio="none" style={{width: '100%', height, overflow: 'visible'}}>
      <path d={`M ${PAD} ${PAD} V ${height - PAD} H ${WIDTH - PAD}`} fill="none" stroke={muted} strokeWidth="1" opacity="0.55" />
      <path d={`M ${PAD} ${height / 2} H ${WIDTH - PAD}`} fill="none" stroke={muted} strokeWidth="1" opacity="0.2" strokeDasharray="3 5" />
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.25" opacity="0.58" />
      {completedCoords.length > 1 ? <path d={completedPath} fill="none" stroke={completed} strokeWidth="1.9" /> : null}
      <path d={`M ${cursorX} ${current.y} V ${height - PAD}`} stroke={highlight} strokeWidth="1" opacity="0.6" />
      <rect x={cursorX - 3} y={current.y - 3} width="6" height="6" fill={highlight} />
    </svg>
  );
};
