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
  const layoutScale = vertical ? height / 1920 : height / 1080;
  const outerPadding = Math.round((vertical ? 42 : 34) * layoutScale);
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

  return (
    <AbsoluteFill
      style={{
        background: 'transparent',
        color: theme.text,
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        padding: outerPadding,
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
          <RouteMap
            points={props.points}
            currentIndex={index}
            theme={theme}
            containerWidth={vertical ? width - 2 * outerPadding : Math.round((width - 2 * outerPadding) * 0.70)}
            containerHeight={vertical ? Math.round((height - 2 * outerPadding) * 0.60) : height - 2 * outerPadding}
            topPadding={Math.round(32 * layoutScale)}
            bottomPadding={Math.round(32 * layoutScale)}
            sidePadding={Math.round(32 * layoutScale)}
            transparent
            showGrid={false}
            visualScale={layoutScale}
          />
        </div>

        <div
          style={{
            minHeight: 0,
            borderRight: `1px solid ${theme.border}`,
            borderBottom: `1px solid ${theme.border}`,
            borderTop: vertical ? 'none' : `1px solid ${theme.border}`,
            background: theme.surface,
          }}
        >
          <TelemetryPanel spec={props} point={point} progress={progress} theme={theme} vertical={vertical} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
