import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {BackgroundLayer} from '../components/BackgroundLayer';
import {RouteMap} from '../components/RouteMap';
import {themes} from '../design/tokens';
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

  return (
    <AbsoluteFill
      style={{
        background: theme.canvas,
        color: theme.text,
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      }}
    >
      <BackgroundLayer background={props.background} />
      <RouteMap points={props.points} currentIndex={currentIndex} theme={theme} transparent={hasBackground} />
      <div
        style={{
          position: 'absolute',
          top: vertical ? 54 : 52,
          left: vertical ? 56 : 64,
          right: vertical ? 56 : 64,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 28,
        }}
      >
        <div style={{minWidth: 0}}>
          {props.activity.title ? (
            <div style={{fontSize: vertical ? 36 : 39, fontWeight: 650, lineHeight: 1.08, letterSpacing: '-0.035em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
              {props.activity.title}
            </div>
          ) : null}
          <div style={{marginTop: props.activity.title ? 9 : 0, color: theme.textSecondary, fontSize: 15, lineHeight: 1.3}}>
            {props.activity.date ? `${date(props.activity.date)} · ` : ''}
            {number(props.summary.distanceKm, 1)} km · +{number(props.summary.elevationGainM)} m
          </div>
        </div>
      </div>
      {props.show_progress_bar !== false ? (
        <div style={{position: 'absolute', left: vertical ? 56 : 64, right: vertical ? 56 : 64, bottom: vertical ? 52 : 44}}>
          <div style={{display: 'flex', justifyContent: 'space-between', color: theme.textMuted, fontSize: 11, fontWeight: 700, letterSpacing: '0.11em', textTransform: 'uppercase', marginBottom: 10}}>
            <span>{t('progress')}</span><span>{Math.round(progress * 100)}%</span>
          </div>
          <div style={{height: 2, background: theme.border}}>
            <div style={{height: '100%', width: `${progress * 100}%`, background: theme.route}} />
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
