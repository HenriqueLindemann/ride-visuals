import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {RouteMap} from '../components/RouteMap';
import {TelemetryPanel} from '../components/TelemetryPanel';
import {themes} from '../design/tokens';
import {pointAtProgress} from '../lib/telemetry';
import type {ActivityRenderSpec} from '../schema';

export const ActivityOverlay = (props: ActivityRenderSpec) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const theme = themes[props.theme];
  const vertical = height > width;
  const animationFrames = Math.round(props.profile.duration_seconds * fps);
  const linear = interpolate(frame, [0, animationFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const progress = linear * linear * (3 - 2 * linear);
  const index = pointAtProgress(props.points, progress, props.summary.sourceDurationSeconds);
  const point = props.points[index];

  return (
    <AbsoluteFill
      style={{
        background: 'transparent',
        color: theme.text,
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        padding: vertical ? 42 : 34,
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'grid',
          gridTemplateColumns: vertical ? '1fr' : '70% 30%',
          gridTemplateRows: vertical ? '60% 40%' : '1fr',
        }}
      >
        <div
          style={{
            minHeight: 0,
            border: `1px solid ${theme.border}`,
            background: 'transparent',
          }}
        >
          <RouteMap points={props.points} currentIndex={index} theme={theme} transparent showGrid={false} />
        </div>
        <div
          style={{
            minHeight: 0,
            borderRight: `1px solid ${theme.border}`,
            borderBottom: `1px solid ${theme.border}`,
            borderTop: vertical ? 'none' : `1px solid ${theme.border}`,
            background: 'rgba(5, 5, 5, 0.30)',
          }}
        >
          <TelemetryPanel spec={props} point={point} progress={progress} theme={theme} vertical={vertical} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
