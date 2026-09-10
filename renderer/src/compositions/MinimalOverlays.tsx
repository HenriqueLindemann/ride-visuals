import {useMemo} from 'react';
import {AbsoluteFill, useVideoConfig} from 'remotion';
import {RouteMap} from '../components/RouteMap';
import {FONT_FAMILY} from '../design/layout';
import {themes} from '../design/tokens';
import {useActivityTimeline} from '../lib/activityTimeline';
import type {ActivityRenderSpec, TelemetryPoint} from '../schema';

// Route geometry stays continuous; numeric readouts may hold their last sample.
const useOverlayPoint = (spec: ActivityRenderSpec) => {
  const timeline = useActivityTimeline(spec);
  const index = spec.outputMode === 'static-summary' ? spec.points.length - 1 : timeline.index;
  return {index, point: spec.points[index]};
};

export const RouteOverlay = (spec: ActivityRenderSpec) => {
  const {index} = useOverlayPoint(spec);
  const {width, height} = useVideoConfig();
  const scale = Math.min(width, height) / 1080;
  return (
    <AbsoluteFill>
      <RouteMap points={spec.points} currentIndex={index} theme={themes[spec.theme]}
        transparent showGrid={false} showBackgroundRoute={false} showCursor={false}
        topPadding={24 * scale} bottomPadding={24 * scale} sidePadding={24 * scale}
        visualScale={scale} completedStrokeWidth={7} />
    </AbsoluteFill>
  );
};

const ElevationTrace = ({points, index, color}: {
  points: TelemetryPoint[]; index: number; color: string;
}) => {
  const geometry = useMemo(() => {
    const elevations = points.flatMap((p) => p.altitudeM === null ? [] : [p.altitudeM]);
    const min = Math.min(...elevations);
    const range = Math.max(1, Math.max(...elevations) - min);
    const distance = points[points.length - 1].distanceKm;
    const duration = Math.max(1, points[points.length - 1].elapsedSeconds);
    const distanceAxis = distance !== null && distance > 0 && points.every((p) => p.distanceKm !== null);
    return points.map((p) => p.altitudeM === null ? null : ({
      x: 4 + 992 * (distanceAxis ? p.distanceKm! / distance! : p.elapsedSeconds / duration),
      y: 92 - 84 * (p.altitudeM - min) / range,
    }));
  }, [points]);
  // Null samples break the line instead of inventing terrain across missing data.
  const path = (end: number) => {
    let penDown = false;
    return geometry.slice(0, end + 1).map((p) => {
      if (!p) { penDown = false; return ''; }
      const command = `${penDown ? 'L' : 'M'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
      penDown = true;
      return command;
    }).join(' ');
  };
  return <svg width="100%" height="100%" viewBox="0 0 1000 100" preserveAspectRatio="none">
    <path d={path(index)} fill="none" stroke={color} strokeWidth={4}
      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
  </svg>;
};

export const StatsOverlay = (spec: ActivityRenderSpec) => {
  const timeline = useActivityTimeline(spec, 0.3);
  const index = spec.outputMode === 'static-summary' ? spec.points.length - 1 : timeline.index;
  const point = spec.outputMode === 'static-summary' ? spec.points[index] : timeline.point;
  const {width, height} = useVideoConfig();
  const vertical = height > width;
  const theme = themes[spec.theme];
  // A soft halo separates text from footage without outlining the glyphs.
  // Keep it on text containers so it never affects the elevation trace.
  const textShadow = `0 1px 3px ${theme.canvas}99, 0 0 8px ${theme.canvas}40`;
  const pt = spec.locale === 'pt-BR';
  const format = (value: number | null, digits = 0) => value === null ? '—' :
    value.toLocaleString(spec.locale, {minimumFractionDigits: digits, maximumFractionDigits: digits});
  const hasHeartRate = spec.points.some((p) => p.heartRateBpm !== null);
  const hasElevation = spec.points.some((p) => p.altitudeM !== null);
  const slots = useMemo(() => {
    const chars = (values: Array<number | null>, digits: number) => Math.max(1,
      ...values.map((value) => value === null ? 1 : value.toLocaleString(spec.locale, {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
      }).length));
    return {
      'km/h': chars(spec.points.map((p) => p.speed3MinKmh ?? p.speedKmh), 1),
      km: chars(spec.points.map((p) => p.distanceKm), 1),
      bpm: chars(spec.points.map((p) => p.heartRateBpm), 0),
    };
  }, [spec.points, spec.locale]);
  const metrics = [
    {label: pt ? 'VELOCIDADE' : 'SPEED', value: format(point.speed3MinKmh ?? point.speedKmh, 1), unit: 'km/h' as const},
    {label: pt ? 'DISTÂNCIA' : 'DISTANCE', value: format(point.distanceKm, 1), unit: 'km' as const},
    ...(hasHeartRate ? [{label: pt ? 'FREQUÊNCIA' : 'HEART RATE', value: format(point.heartRateBpm), unit: 'bpm' as const}] : []),
  ];
  return <AbsoluteFill style={{fontFamily: FONT_FAMILY, color: theme.text, padding: 24,
    boxSizing: 'border-box', display: 'flex', gap: 24, justifyContent: 'center'}}>
    <div style={{display: 'flex', flexDirection: vertical ? 'column' : 'row', gap: vertical ? 24 : 40,
      textShadow}}>
      {metrics.map((metric) => <div key={metric.unit} style={{flex: 1, minWidth: 0}}>
        <div style={{fontSize: 13, fontWeight: 600, letterSpacing: 2, color: theme.textSecondary}}>{metric.label}</div>
        <div style={{display: 'flex', alignItems: 'baseline', gap: 8, whiteSpace: 'nowrap'}}>
          <span style={{fontSize: 58, lineHeight: 1.15, fontWeight: 600, letterSpacing: -2,
            fontVariantNumeric: 'tabular-nums', display: 'inline-block',
            width: `${slots[metric.unit]}ch`, flexShrink: 0}}>{metric.value}</span>
          <span style={{fontSize: 18, color: theme.textSecondary}}>{metric.unit}</span>
        </div>
      </div>)}
    </div>
    {hasElevation ? <div>
      <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 13,
        letterSpacing: 2, color: theme.textSecondary, marginBottom: 12, textShadow}}>
        <span>{pt ? 'ALTIMETRIA' : 'ELEVATION'}</span>
        <span style={{letterSpacing: 0, fontVariantNumeric: 'tabular-nums'}}>{format(point.altitudeM)} m</span>
      </div>
      <div style={{height: vertical ? 100 : 88}}>
        <ElevationTrace points={spec.points} index={index} color={theme.route} />
      </div>
    </div> : null}
  </AbsoluteFill>;
};
