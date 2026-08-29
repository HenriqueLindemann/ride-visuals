import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {BackgroundLayer} from '../components/BackgroundLayer';
import {RouteMap} from '../components/RouteMap';
import {themes} from '../design/tokens';
import {FONT_FAMILY, landscapeSafeInsets} from '../design/layout';
import {createI18n} from '../i18n/messages';
import {pointAtProgress} from '../lib/telemetry';
import type {ActivityRenderSpec} from '../schema';

export const ActivityClean = (props: ActivityRenderSpec) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const theme = themes[props.theme];
  const {number, date, t} = createI18n(props.locale);
  const vertical = height > width;
  const animationFrames = Math.round(props.profile.duration_seconds * fps);
  const linear = interpolate(frame, [0, animationFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const progress = linear * linear * (3 - 2 * linear);
  const currentIndex = pointAtProgress(props.points, progress, props.summary.sourceDurationSeconds);
  const hasBackground = props.background !== null;
  const scaleFactor = vertical ? height / 1920 : height / 1080;
  const topPadding = vertical ? Math.round(150 * scaleFactor) : Math.round(140 * scaleFactor);
  const bottomPadding = props.show_progress_bar
    ? Math.round(75 * scaleFactor)
    : Math.round(48 * scaleFactor);
  const sidePadding = vertical ? Math.round(48 * scaleFactor) : Math.round(64 * scaleFactor);
  const safeInsets = landscapeSafeInsets(props.presentation);

  return (
    <AbsoluteFill
      style={{
        background: theme.canvas,
        color: theme.text,
        fontFamily: FONT_FAMILY,
      }}
    >
      <BackgroundLayer background={props.background} presentation={props.presentation} />
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
          points={props.points}
          currentIndex={currentIndex}
          theme={theme}
          topPadding={topPadding}
          bottomPadding={bottomPadding}
          sidePadding={sidePadding}
          transparent={hasBackground}
          showBackgroundRoute={props.show_background_route}
          visualScale={scaleFactor}
        />
      </div>

      <div
        style={{
          position: 'absolute',
          top: Math.round((vertical ? 54 : 52) * scaleFactor),
          left: safeInsets.left + Math.round((vertical ? 56 : 64) * scaleFactor),
          right: safeInsets.right + Math.round((vertical ? 56 : 64) * scaleFactor),
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: Math.round(28 * scaleFactor),
        }}
      >
        <div style={{minWidth: 0}}>
          {props.activity.title ? (
            <div
              style={{
                fontSize: Math.round((vertical ? 36 : 38) * scaleFactor),
                fontWeight: 650,
                lineHeight: 1.08,
                letterSpacing: '-0.035em',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {props.activity.title}
            </div>
          ) : null}
          <div
            style={{
              marginTop: props.activity.title ? 9 * scaleFactor : 0,
              color: theme.textSecondary,
              fontSize: 15 * scaleFactor,
              lineHeight: 1.3,
            }}
          >
            {props.activity.date ? `${date(props.activity.date)} · ` : ''}
            {number(props.summary.distanceKm, 1)} km · +{number(props.summary.elevationGainM)} m
          </div>
        </div>
      </div>
      {props.show_progress_bar === true ? (
        <div
          style={{
            position: 'absolute',
            left: safeInsets.left + (vertical ? 56 : 64) * scaleFactor,
            right: safeInsets.right + (vertical ? 56 : 64) * scaleFactor,
            bottom: (vertical ? 52 : 44) * scaleFactor,
          }}
        >
          <div style={{display: 'flex', justifyContent: 'space-between', color: theme.textMuted, fontSize: 11 * scaleFactor, fontWeight: 700, letterSpacing: '0.11em', textTransform: 'uppercase', marginBottom: 10 * scaleFactor}}>
            <span>{t('progress')}</span><span>{Math.round(progress * 100)}%</span>
          </div>
          <div style={{height: Math.max(1, 2 * scaleFactor), background: theme.border}}>
            <div style={{height: '100%', width: `${progress * 100}%`, background: theme.route}} />
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
