import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {BackgroundLayer} from '../components/BackgroundLayer';
import {RouteMap} from '../components/RouteMap';
import {TelemetryPanel} from '../components/TelemetryPanel';
import {themes} from '../design/tokens';
import {pointAtProgress} from '../lib/telemetry';
import type {ActivityRenderSpec} from '../schema';

export const ActivityTelemetry = (props: ActivityRenderSpec) => {
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
  const readoutStep = 0.2 / props.profile.duration_seconds;
  const steppedProgress = progress > 1 - readoutStep ? 1 : Math.floor(progress / readoutStep) * readoutStep;
  const point = props.points[pointAtProgress(props.points, steppedProgress, props.summary.sourceDurationSeconds)];
  const hasBackground = props.background !== null;

  return (
    <AbsoluteFill
      style={{
        background: theme.canvas,
        color: theme.text,
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      }}
    >
      <BackgroundLayer background={props.background} />
      <AbsoluteFill
        style={{
          display: 'grid',
          gridTemplateColumns: vertical ? '1fr' : '70% 30%',
          gridTemplateRows: vertical ? '60% 40%' : '1fr',
          background: 'transparent',
        }}
      >
        <RouteMap points={props.points} currentIndex={index} theme={theme} transparent={hasBackground} />
        <div
          style={{
            minHeight: 0,
            background: hasBackground ? 'rgba(5, 5, 5, 0.80)' : theme.panel,
            borderLeft: vertical ? 'none' : `1px solid ${theme.border}`,
            borderTop: vertical ? `1px solid ${theme.border}` : 'none',
          }}
        >
          <TelemetryPanel spec={props} point={point} progress={progress} theme={theme} vertical={vertical} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
