import type {TelemetryPoint} from '../schema';

export const lastNumber = (points: TelemetryPoint[], key: keyof TelemetryPoint) => {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const value = points[index][key];
    if (typeof value === 'number') return value;
  }
  return null;
};

export const pointAtProgress = (
  points: TelemetryPoint[],
  progress: number,
  sourceDuration: number,
) => {
  const target = sourceDuration * progress;
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].elapsedSeconds < target) low = middle + 1;
    else high = middle;
  }
  return low;
};

export const trail = (
  points: TelemetryPoint[],
  index: number,
  key: keyof TelemetryPoint,
  seconds = 180,
) => {
  const startTime = Math.max(0, points[index].elapsedSeconds - seconds);
  let start = index;
  while (start > 0 && points[start].elapsedSeconds > startTime) start -= 1;
  const selected = points.slice(start, index + 1);
  const stride = Math.max(1, Math.floor(selected.length / 72));
  return selected.filter((_, itemIndex) => itemIndex % stride === 0).map((point) => {
    const value = point[key];
    return typeof value === 'number' ? value : null;
  });
};
