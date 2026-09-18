import {AbsoluteFill, useVideoConfig} from 'remotion';
import {BackgroundLayer} from '../components/BackgroundLayer';
import {RouteMap} from '../components/RouteMap';
import {FONT_FAMILY, landscapeSafeInsets} from '../design/layout';
import {themes} from '../design/tokens';
import {createI18n} from '../i18n/messages';
import {useActivityTimeline} from '../lib/activityTimeline';
import type {ActivityRenderSpec} from '../schema';

export const ActivityMinimalOverlay = (spec: ActivityRenderSpec) => (
  <ActivityMinimal {...spec} transparent />
);

export const ActivityMinimal = (spec: ActivityRenderSpec & {transparent?: boolean}) => {
  const {width, height} = useVideoConfig();
  const vertical = height > width;
  const scale = vertical ? height / 1920 : height / 1080;
  const theme = themes[spec.theme];
  const {t} = createI18n(spec.locale);
  const hasBackground = spec.background !== null;
  const safeInsets = landscapeSafeInsets(spec.presentation);

  const timeline = useActivityTimeline(spec, 0.3);
  const index = spec.outputMode === 'static-summary' ? spec.points.length - 1 : timeline.index;
  const point = spec.outputMode === 'static-summary' ? spec.points[index] : timeline.point;

  const textShadow = '0 2px 12px rgba(0, 0, 0, 0.95), 0 1px 3px rgba(0, 0, 0, 0.95)';
  const format = (value: number | null, digits = 0) =>
    value === null
      ? '—'
      : value.toLocaleString(spec.locale, {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });

  const speedVal = format(point.speed3MinKmh ?? point.speedKmh, 1);
  const distanceVal = format(point.distanceKm, 1);

  // In vertical, reserve bottom 360px for the metrics HUD (elevated ~150px for Insta UI safe zone)
  const routeBottomPadding = vertical ? 360 * scale : 48 * scale;
  const routeTopPadding = vertical ? 120 * scale : 48 * scale;
  const routeSidePadding = 48 * scale;

  return (
    <AbsoluteFill
      style={{
        background: spec.transparent || hasBackground ? 'transparent' : theme.canvas,
        color: theme.text,
        fontFamily: FONT_FAMILY,
      }}
    >
      {!spec.transparent && (
        <BackgroundLayer background={spec.background} presentation={spec.presentation} />
      )}

      {/* Floating animated route */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: safeInsets.left,
          right: safeInsets.right,
        }}
      >
        <RouteMap
          points={spec.points}
          currentIndex={index}
          theme={theme}
          topPadding={routeTopPadding}
          bottomPadding={routeBottomPadding}
          sidePadding={routeSidePadding}
          transparent={true}
          showGrid={false}
          showBackgroundRoute={spec.show_background_route}
          showCursor={false}
          visualScale={scale}
          completedStrokeWidth={7}
        />
      </div>

      {/* Ultra-minimal metrics HUD: Speed and Distance only (elevated ~150px for Insta UI safe zone) */}
      <div
        style={{
          position: 'absolute',
          bottom: vertical ? Math.round(210 * scale) : Math.round(48 * scale),
          left: vertical ? Math.round(54 * scale) : 'auto',
          right: Math.round(54 * scale),
          display: 'flex',
          gap: Math.round(54 * scale),
          alignItems: 'flex-end',
          textShadow,
          zIndex: 10,
        }}
      >
        {/* Speed */}
        <div style={{minWidth: Math.round(240 * scale)}}>
          <div
            style={{
              fontSize: Math.round(18 * scale),
              fontWeight: 700,
              letterSpacing: 2.5,
              color: theme.textSecondary,
              marginBottom: Math.round(4 * scale),
            }}
          >
            {t('minimalSpeed')}
          </div>
          <div style={{display: 'flex', alignItems: 'baseline', gap: Math.round(10 * scale)}}>
            <span
              style={{
                fontSize: Math.round(76 * scale),
                lineHeight: 1.0,
                fontWeight: 700,
                letterSpacing: -1.5,
                fontVariantNumeric: 'tabular-nums',
                color: '#FFFFFF',
              }}
            >
              {speedVal}
            </span>
            <span
              style={{
                fontSize: Math.round(24 * scale),
                color: theme.textSecondary,
                fontWeight: 600,
              }}
            >
              km/h
            </span>
          </div>
        </div>

        {/* Distance */}
        <div style={{minWidth: Math.round(240 * scale)}}>
          <div
            style={{
              fontSize: Math.round(18 * scale),
              fontWeight: 700,
              letterSpacing: 2.5,
              color: theme.textSecondary,
              marginBottom: Math.round(4 * scale),
            }}
          >
            {t('minimalDistance')}
          </div>
          <div style={{display: 'flex', alignItems: 'baseline', gap: Math.round(10 * scale)}}>
            <span
              style={{
                fontSize: Math.round(76 * scale),
                lineHeight: 1.0,
                fontWeight: 700,
                letterSpacing: -1.5,
                fontVariantNumeric: 'tabular-nums',
                color: '#FFFFFF',
              }}
            >
              {distanceVal}
            </span>
            <span
              style={{
                fontSize: Math.round(24 * scale),
                color: theme.textSecondary,
                fontWeight: 600,
              }}
            >
              km
            </span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
