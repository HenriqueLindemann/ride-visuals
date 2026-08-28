import {useMemo} from 'react';
import {useVideoConfig} from 'remotion';
import type {Theme} from '../design/tokens';
import {createI18n} from '../i18n/messages';
import type {ActivityRenderSpec, TelemetryPoint} from '../schema';
import {ProgressAxisChart} from './ProgressAxisChart';

type Props = {
  spec: ActivityRenderSpec;
  point: TelemetryPoint;
  progress: number;
  theme: Theme;
  vertical: boolean;
};

const LANDSCAPE_METRICS_HEIGHT = '72%';

const elapsed = (seconds: number) => {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${hours}:${String(minutes).padStart(2, '0')}`;
};

const Label = ({children, theme, s = 1, minSize = 11}: {children: string; theme: Theme; s?: number; minSize?: number}) => (
  <div
    style={{
      color: theme.textMuted,
      fontSize: Math.max(7, Math.round(minSize * s)),
      fontWeight: 700,
      letterSpacing: '0.09em',
      textTransform: 'uppercase',
      lineHeight: 1.2,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
    }}
  >
    {children}
  </div>
);

const Stat = ({
  label,
  value,
  unit,
  theme,
  leftBorder = false,
  centered = false,
  s = 1,
}: {
  label: string;
  value: string;
  unit?: string;
  theme: Theme;
  leftBorder?: boolean;
  centered?: boolean;
  s?: number;
}) => (
  <div
    style={{
      borderTop: `1px solid ${theme.border}`,
      borderLeft: leftBorder ? `1px solid ${theme.border}` : undefined,
      padding: `${Math.round(12 * s)}px ${Math.round(14 * s)}px ${Math.round(10 * s)}px`,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      minWidth: 0,
    }}
  >
    <div style={{minHeight: Math.max(16, Math.round(18 * s)), display: 'flex', alignItems: 'center'}}>
      <Label theme={theme} s={s}>{label}</Label>
    </div>
    <div
      style={{
        marginTop: Math.round(4 * s),
        color: theme.text,
        fontSize: Math.max(24, Math.round(32 * s)),
        fontWeight: 600,
        lineHeight: 1.1,
        letterSpacing: '-0.025em',
        fontVariantNumeric: 'tabular-nums',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {value}
      {unit ? (
        <span
          style={{
            marginLeft: Math.round(5 * s),
            color: theme.textMuted,
            fontSize: Math.max(11, Math.round(13 * s)),
            fontWeight: 600,
          }}
        >
          {unit}
        </span>
      ) : null}
    </div>
  </div>
);

export const TelemetryPanel = ({spec, point, progress, theme, vertical}: Props) => {
  const {height} = useVideoConfig();
  const s = vertical ? height / 1920 : height / 1080;
  const {t, number, date} = createI18n(spec.locale);
  const staticSummary = spec.outputMode === 'static-summary';
  const landscape = !vertical;

  const numericMean = (values: Array<number | null>): number | null => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? valid.reduce((total, value) => total + value, 0) / valid.length : null;
  };
  const numericMax = (values: Array<number | null>): number | null => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? Math.max(...valid) : null;
  };
  const numericMin = (values: Array<number | null>): number | null => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? Math.min(...valid) : null;
  };
  const measurement = (value: number | null | undefined, decimals = 0) =>
    value !== null && value !== undefined && Number.isFinite(value) ? number(value, decimals) : '—';

  const speedSeries = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.speed3MinKmh), [spec.points]);
  const heartRateSeries = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.heartRateBpm), [spec.points]);
  const speed = staticSummary
    ? numericMean(spec.points.map((telemetryPoint) => telemetryPoint.speedKmh))
    : point.speed3MinKmh ?? point.speedKmh;
  const heartRate = staticSummary ? numericMean(heartRateSeries) : point.heartRateBpm;
  const altitudeProfile = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.altitudeM), [spec.points]);
  const runningAscentM = point.cumulativeElevationGainM;
  const ascentValue =
    !staticSummary && runningAscentM !== null && runningAscentM !== undefined
      ? Math.round(runningAscentM)
      : spec.summary.elevationGainM;

  const hasTemperature = spec.points.some(
    (telemetryPoint) => telemetryPoint.temperatureC !== null && telemetryPoint.temperatureC !== undefined && Number.isFinite(telemetryPoint.temperatureC)
  );
  const hasPower = spec.points.some(
    (telemetryPoint) => telemetryPoint.powerWatts !== null && telemetryPoint.powerWatts !== undefined && Number.isFinite(telemetryPoint.powerWatts)
  );
  const hasHeartRate = heartRateSeries.some(
    (value) => value !== null && value !== undefined && Number.isFinite(value)
  );

  const fourthCurrentStat = hasTemperature
    ? {label: t('temperature'), value: measurement(point.temperatureC, 1), unit: '°C'}
    : {label: t('ascent'), value: number(ascentValue), unit: 'm'};

  const fifthCurrentStat = hasPower
    ? {label: t('power'), value: measurement(point.powerWatts), unit: 'W'}
    : (hasTemperature
        ? {label: t('ascent'), value: number(ascentValue), unit: 'm'}
        : {label: t('averageSpeed'), value: measurement(speed, 1), unit: 'km/h'});

  const currentStats = [
    {label: t('distance'), value: measurement(point.distanceKm, 1), unit: 'km'},
    {label: t('altitude'), value: measurement(point.altitudeM), unit: 'm'},
    {label: t('grade'), value: measurement(point.gradePct, 1), unit: '%'},
    fourthCurrentStat,
    fifthCurrentStat,
    {label: t('totalTime'), value: elapsed(point.elapsedSeconds), unit: 'h'},
  ];

  const fourthSummaryStat = hasTemperature
    ? {label: t('averageTemperature'), value: measurement(numericMean(spec.points.map((p) => p.temperatureC)), 1), unit: '°C'}
    : {label: t('ascent'), value: number(spec.summary.elevationGainM), unit: 'm'};

  const fifthSummaryStat = hasPower
    ? {label: t('averagePower'), value: measurement(numericMean(spec.points.map((p) => p.powerWatts))), unit: 'W'}
    : (hasTemperature
        ? {label: t('ascent'), value: number(spec.summary.elevationGainM), unit: 'm'}
        : {label: t('averageSpeed'), value: measurement(numericMean(spec.points.map((p) => p.speedKmh)), 1), unit: 'km/h'});

  const summaryStats = [
    {label: t('distance'), value: number(spec.summary.distanceKm, 1), unit: 'km'},
    {label: t('maximumAltitude'), value: measurement(numericMax(altitudeProfile)), unit: 'm'},
    {label: t('maximumGrade'), value: measurement(spec.summary.maximumGradePct, 1), unit: '%'},
    fourthSummaryStat,
    fifthSummaryStat,
    {label: t('totalTime'), value: elapsed(spec.summary.sourceDurationSeconds), unit: 'h'},
  ];
  const stats = staticSummary ? summaryStats : currentStats;

  const header = (
    <div
      style={{
        height: landscape ? '100%' : undefined,
        boxSizing: 'border-box',
        paddingBottom: Math.round((vertical ? 14 : 18) * s),
        display: landscape ? 'flex' : undefined,
        flexDirection: landscape ? 'column' : undefined,
        justifyContent: landscape ? 'center' : undefined,
      }}
    >
      {spec.activity.title ? (
        <div
          style={{
            fontSize: Math.max(16, Math.min(Math.round((vertical ? 28 : 28) * s), Math.round(520 * s / Math.max(14, (spec.activity.title || '').length)))),
            fontWeight: 650,
            lineHeight: 1.15,
            letterSpacing: '-0.03em',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {spec.activity.title}
        </div>
      ) : null}
      <div
        style={{
          fontSize: Math.max(11, Math.round(13 * s)),
          color: theme.textSecondary,
          marginTop: spec.activity.title ? Math.round(6 * s) : 0,
          lineHeight: 1.3,
        }}
      >
        {spec.activity.date ? `${date(spec.activity.date)} · ` : ''}
        {number(spec.summary.distanceKm, 1)} km · +{number(spec.summary.elevationGainM)} m
      </div>
    </div>
  );

  const speedBlock = (
    <div
      style={{
        borderTop: `1px solid ${theme.border}`,
        padding: vertical
          ? `${Math.round(12 * s)}px ${Math.round(14 * s)}px ${Math.round(8 * s)}px 0`
          : `${Math.round(14 * s)}px 0 ${Math.round(10 * s)}px`,
        height: landscape ? '100%' : undefined,
        boxSizing: 'border-box',
        display: landscape ? 'flex' : undefined,
        flexDirection: landscape ? 'column' : undefined,
        justifyContent: landscape ? 'center' : undefined,
      }}
    >
      <Label theme={theme} s={s}>{staticSummary ? t('averageSpeed') : t('speed')}</Label>
      <div style={{display: 'flex', flexDirection: 'column', gap: Math.round(8 * s), marginTop: Math.round(6 * s)}}>
        <div
          style={{
            fontSize: Math.max(24, Math.round((vertical ? 40 : 40) * s)),
            fontWeight: 600,
            lineHeight: 1,
            letterSpacing: '-0.04em',
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}
        >
          {measurement(speed, 1)}
          <span style={{fontSize: Math.max(11, Math.round(13 * s)), color: theme.textMuted, marginLeft: Math.round(6 * s), fontWeight: 500}}>km/h</span>
        </div>
        <ProgressAxisChart
          values={speedSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.text}
          muted={theme.border}
          height={Math.max(52, Math.round((vertical ? 68 : 64) * s))}
        />
      </div>
    </div>
  );

  const heartBlock = hasHeartRate ? (
    <div
      style={{
        borderTop: `1px solid ${theme.border}`,
        borderLeft: vertical ? `1px solid ${theme.border}` : undefined,
        padding: vertical
          ? `${Math.round(12 * s)}px 0 ${Math.round(8 * s)}px ${Math.round(14 * s)}px`
          : `${Math.round(12 * s)}px 0 ${Math.round(10 * s)}px`,
        height: landscape ? '100%' : undefined,
        boxSizing: 'border-box',
        display: landscape ? 'flex' : undefined,
        flexDirection: landscape ? 'column' : undefined,
        justifyContent: landscape ? 'center' : undefined,
      }}
    >
      <Label theme={theme} s={s}>{staticSummary ? t('averageHeartRate') : t('heartRate')}</Label>
      <div style={{display: 'flex', flexDirection: 'column', gap: Math.round(8 * s), marginTop: Math.round(6 * s)}}>
        <div
          style={{
            fontSize: Math.max(22, Math.round((vertical ? 34 : 34) * s)),
            fontWeight: 600,
            lineHeight: 1,
            letterSpacing: '-0.04em',
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}
        >
          {measurement(heartRate)}
          <span style={{fontSize: Math.max(11, Math.round(13 * s)), color: theme.textMuted, marginLeft: Math.round(5 * s), fontWeight: 500}}>bpm</span>
        </div>
        <ProgressAxisChart
          values={heartRateSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.text}
          muted={theme.border}
          height={Math.max(52, Math.round((vertical ? 68 : 64) * s))}
        />
      </div>
    </div>
  ) : null;

  return (
    <div
      style={{
        height: '100%',
        boxSizing: 'border-box',
        padding: vertical
          ? `${Math.round(20 * s)}px ${Math.round(28 * s)}px ${Math.round(18 * s)}px`
          : `${Math.round(28 * s)}px ${Math.round(28 * s)}px ${Math.round(20 * s)}px`,
        display: 'flex',
        flexDirection: 'column',
        color: theme.text,
      }}
    >
      <div
        style={landscape ? {
          height: LANDSCAPE_METRICS_HEIGHT,
          display: 'grid',
          gridTemplateRows: hasHeartRate ? 'auto auto auto minmax(0, 1fr)' : 'auto auto minmax(0, 1fr)',
        } : undefined}
      >
        {header}
        <div style={vertical ? {display: 'grid', gridTemplateColumns: '1fr 1fr'} : landscape ? {display: 'contents'} : undefined}>
          {speedBlock}
          {heartBlock}
        </div>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)'}}>
          {stats.map((stat, statIndex) => (
            <Stat
              key={stat.label}
              {...stat}
              theme={theme}
              leftBorder={statIndex % 3 !== 0}
              centered={landscape}
              s={s}
            />
          ))}
        </div>

      </div>

      <div
        style={{
          borderTop: `1px solid ${theme.border}`,
          padding: `${Math.round(12 * s)}px 0 ${Math.round(8 * s)}px`,
          marginTop: Math.round(12 * s),
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: Math.round(6 * s)}}>
          <Label theme={theme} s={s}>{t('elevationProfile')}</Label>
          <div style={{fontSize: Math.max(11, Math.round(14 * s)), fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: theme.textSecondary}}>
            {staticSummary
              ? `${measurement(numericMin(altitudeProfile))}–${measurement(numericMax(altitudeProfile))} m`
              : `${measurement(point.altitudeM)} m`}
          </div>
        </div>
        <div style={{flex: 1, minHeight: 0, display: 'flex', alignItems: 'center'}}>
          <ProgressAxisChart
            values={altitudeProfile}
            progress={progress}
            stroke={theme.textMuted}
            completed={theme.text}
            highlight={theme.text}
            muted={theme.border}
            height={Math.max(vertical ? 100 : 90, Math.round(180 * s))}
            smoothingSamples={3}
          />
        </div>
      </div>

      {spec.show_progress_bar === true ? (
        <div style={{paddingTop: Math.round(10 * s)}}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              color: theme.textMuted,
              fontSize: Math.max(9, Math.round(10 * s)),
              fontWeight: 700,
              letterSpacing: '0.11em',
              textTransform: 'uppercase',
              marginBottom: Math.round(6 * s),
            }}
          >
            <span>{t('progress')}</span>
            <span>{Math.round(progress * 100)}%</span>
          </div>
          <div style={{height: 2, background: theme.border}}>
            <div style={{height: '100%', width: `${progress * 100}%`, background: theme.route}} />
          </div>
        </div>
      ) : null}
    </div>
  );
};
