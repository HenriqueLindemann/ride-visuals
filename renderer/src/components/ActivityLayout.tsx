import {AbsoluteFill, useVideoConfig} from 'remotion';
import {BackgroundLayer} from './BackgroundLayer';
import {RouteMap} from './RouteMap';
import {TelemetryPanel} from './TelemetryPanel';
import {themes} from '../design/tokens';
import {
  FONT_FAMILY,
  INSTAGRAM_PANEL_SHARE,
  MAP_SHARE_PORTRAIT,
  PANEL_SHARE_LANDSCAPE,
  landscapeSafeInsets,
  mapPadding,
} from '../design/layout';
import {useActivityTimeline} from '../lib/activityTimeline';
import type {ActivityRenderSpec} from '../schema';

type Props = {
  spec: ActivityRenderSpec;
  /** 'overlay' renders the transparent, framed version for compositing over custom footage. */
  variant?: 'full' | 'overlay';
};

export const ActivityLayout = ({spec, variant = 'full'}: Props) => {
  const {width, height} = useVideoConfig();
  const theme = themes[spec.theme];
  const vertical = height > width;
  const scale = vertical ? height / 1920 : height / 1080;
  const overlay = variant === 'overlay';
  const {progress, index, point} = useActivityTimeline(spec);
  const hasBackground = spec.background !== null;
  const divider = `1px solid ${theme.border}`;
  const padding = mapPadding(vertical, scale);
  const safeInsets = landscapeSafeInsets(spec.presentation);
  const panelShare =
    spec.presentation === 'instagram-story-landscape'
      ? INSTAGRAM_PANEL_SHARE
      : PANEL_SHARE_LANDSCAPE;

  const panelChrome = overlay
    ? {
        borderRight: divider,
        borderBottom: divider,
        borderTop: vertical ? undefined : divider,
        background: theme.surface,
      }
    : {
        borderLeft: vertical ? undefined : divider,
        borderTop: vertical ? divider : undefined,
        background: hasBackground ? theme.surface : theme.panel,
      };

  return (
    <AbsoluteFill
      style={{
        background: overlay ? 'transparent' : theme.canvas,
        color: theme.text,
        fontFamily: FONT_FAMILY,
        padding: overlay ? Math.round((vertical ? 42 : 34) * scale) : 0,
        boxSizing: 'border-box',
      }}
    >
      {overlay ? null : (
        <BackgroundLayer background={spec.background} presentation={spec.presentation} />
      )}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: safeInsets.left,
          right: safeInsets.right,
          display: 'grid',
          gridTemplateColumns: vertical ? '1fr' : `${(1 - panelShare) * 100}% ${panelShare * 100}%`,
          gridTemplateRows: vertical ? `${MAP_SHARE_PORTRAIT * 100}% 1fr` : '1fr',
          background: 'transparent',
        }}
      >
        <div
          style={{
            position: 'relative',
            overflow: 'hidden',
            minHeight: 0,
            border: overlay ? divider : undefined,
          }}
        >
          <RouteMap
            points={spec.points}
            currentIndex={index}
            theme={theme}
            topPadding={padding}
            bottomPadding={padding}
            sidePadding={padding}
            transparent={overlay || hasBackground}
            showGrid={!overlay}
            showBackgroundRoute={spec.show_background_route}
            visualScale={scale}
          />
        </div>

        <div style={{minHeight: 0, ...panelChrome}}>
          <TelemetryPanel spec={spec} point={point} progress={progress} theme={theme} vertical={vertical} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
