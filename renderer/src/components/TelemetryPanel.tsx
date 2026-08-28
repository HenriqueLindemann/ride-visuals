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
      // Linear in `s` — floors would break proportionality and truncate labels.
      fontSize: Math.round(minSize * s),
      fontWeight: 700,
      letterSpacing: '0.08em',
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
  alignLeftEdge = false,
  s = 1,
  labelSize = 11,
  portrait = false,
}: {
  label: string;
  value: string;
  unit?: string;
  theme: Theme;
  leftBorder?: boolean;
  alignLeftEdge?: boolean;
  s?: number;
  labelSize?: number;
  portrait?: boolean;
}) => (
  <div
    style={{
      borderTop: `1px solid ${theme.border}`,
      borderLeft: leftBorder ? `1px solid ${theme.border}` : undefined,
      padding: `${Math.round(10 * s)}px ${Math.round(12 * s)}px ${Math.round(8 * s)}px ${alignLeftEdge ? 0 : Math.round(12 * s)}px`,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      minWidth: 0,
    }}
  >
    <div style={{minHeight: Math.round((portrait ? 28 : 16) * s), display: 'flex', alignItems: 'center'}}>
      <Label theme={theme} s={s} minSize={labelSize}>{label}</Label>
    </div>
    <div
      style={{
        marginTop: Math.round(3 * s),
        color: theme.text,
        fontSize: Math.round((portrait ? 56 : 32) * s),
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
            marginLeft: Math.round(4 * s),
            color: theme.textMuted,
            fontSize: Math.round((portrait ? 26 : 14) * s),
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
  // Portrait is consumed on phones: it runs a larger type scale than landscape.
  const labelSize = vertical ? 22 : 12;

  const numericMean = (values: Array<number | null>): number | null => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? valid.reduce((total, value) => total + value, 0) / valid.length : null;
  };
  const numericMax = (values: Array<number | null>): number | null => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? Math.max(...valid) : null;
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
        boxSizing: 'border-box',
        paddingBottom: Math.round((vertical ? 14 : 22) * s),
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      {spec.activity.title ? (
        <div
          style={{
            fontSize: Math.round((vertical ? 44 : 30) * s),
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
          fontSize: Math.round((vertical ? 24 : 15) * s),
          color: theme.textSecondary,
          marginTop: spec.activity.title ? Math.round(5 * s) : 0,
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
          ? `${Math.round(10 * s)}px ${Math.round(14 * s)}px ${Math.round(8 * s)}px 0`
          : `${Math.round(16 * s)}px 0 ${Math.round(14 * s)}px`,
        boxSizing: 'border-box',
        // Landscape: the wave absorbs this block's share of the leftover panel
        // height, so no void ever opens below the chart.
        display: 'flex',
        flexDirection: 'column',
        flex: vertical ? undefined : 1,
        minHeight: 0,
      }}
    >
      <Label theme={theme} s={s} minSize={labelSize}>{staticSummary ? t('averageSpeed') : t('speed')}</Label>
      <div style={{display: 'flex', flexDirection: 'column', gap: Math.round(6 * s), marginTop: Math.round(4 * s), flex: 1, minHeight: 0}}>
        <div
          style={{
            fontSize: Math.round((vertical ? 72 : 48) * s),
            fontWeight: 600,
            lineHeight: 1,
            letterSpacing: '-0.04em',
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}
        >
          {measurement(speed, 1)}
          <span style={{fontSize: Math.round((vertical ? 28 : 16) * s), color: theme.textMuted, marginLeft: Math.round(6 * s), fontWeight: 500}}>km/h</span>
        </div>
        <ProgressAxisChart
          values={speedSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.text}
          muted={theme.border}
          height={vertical ? Math.round(48 * s) : undefined}
          padY={4}
          smoothingSamples={5}
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
          ? `${Math.round(10 * s)}px 0 ${Math.round(8 * s)}px ${Math.round(14 * s)}px`
          : `${Math.round(16 * s)}px 0 ${Math.round(14 * s)}px`,
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        flex: vertical ? undefined : 1,
        minHeight: 0,
      }}
    >
      <Label theme={theme} s={s} minSize={labelSize}>{staticSummary ? t('averageHeartRate') : t('heartRate')}</Label>
      <div style={{display: 'flex', flexDirection: 'column', gap: Math.round(6 * s), marginTop: Math.round(4 * s), flex: 1, minHeight: 0}}>
        <div
          style={{
            fontSize: Math.round((vertical ? 64 : 42) * s),
            fontWeight: 600,
            lineHeight: 1,
            letterSpacing: '-0.04em',
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}
        >
          {measurement(heartRate)}
          <span style={{fontSize: Math.round((vertical ? 26 : 16) * s), color: theme.textMuted, marginLeft: Math.round(5 * s), fontWeight: 500}}>bpm</span>
        </div>
        <ProgressAxisChart
          values={heartRateSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.text}
          muted={theme.border}
          height={vertical ? Math.round(48 * s) : undefined}
          padY={4}
          smoothingSamples={5}
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
          ? `${Math.round(24 * s)}px ${Math.round(28 * s)}px ${Math.round(20 * s)}px`
          : `${Math.round(32 * s)}px ${Math.round(28 * s)}px ${Math.round(28 * s)}px`,
        display: 'flex',
        flexDirection: 'column',
        color: theme.text,
      }}
    >
      <div style={vertical ? undefined : {flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column'}}>
        {header}
        <div style={vertical ? {display: 'grid', gridTemplateColumns: '1fr 1fr'} : {flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column'}}>
          {speedBlock}
          {heartBlock}
        </div>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)'}}>
        {stats.map((stat, statIndex) => (
          <Stat
            key={stat.label}
            {...stat}
            theme={theme}
            leftBorder={statIndex % 3 !== 0}
            alignLeftEdge={statIndex % 3 === 0}
            labelSize={labelSize}
            portrait={vertical}
            s={s}
          />
        ))}
      </div>

      <div
        style={{
          borderTop: `1px solid ${theme.border}`,
          paddingTop: Math.round(10 * s),
          paddingBottom: 0,
          marginTop: Math.round(10 * s),
          display: 'flex',
          flexDirection: 'column',
          // Portrait: the profile grows into every leftover pixel. Landscape:
          // fixed height — the root's space-between owns the breathing room.
          flex: vertical ? 1 : undefined,
          minHeight: 0,
        }}
      >
        <div style={{marginBottom: Math.round(8 * s)}}>
          <Label theme={theme} s={s} minSize={labelSize}>{t('elevationProfile')}</Label>
        </div>
        {/* Fills every pixel the section has left — no fixed height, no dead space. */}
        <ProgressAxisChart
          values={altitudeProfile}
          progress={progress}
          stroke={theme.textMuted}
          completed={theme.text}
          highlight={theme.text}
          muted={theme.border}
          height={vertical ? undefined : Math.round(280 * s)}
          padX={6}
          padY={vertical ? 14 : 10}
          smoothingSamples={3}
        />
      </div>

      {spec.show_progress_bar === true ? (
        <div style={{paddingTop: Math.round(8 * s)}}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              color: theme.textMuted,
              fontSize: Math.round((vertical ? 18 : 11) * s),
              fontWeight: 700,
              letterSpacing: '0.11em',
              textTransform: 'uppercase',
              marginBottom: Math.round(4 * s),
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
