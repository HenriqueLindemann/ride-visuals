import {useMemo} from 'react';
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

const Label = ({children, theme}: {children: string; theme: Theme}) => (
  <div style={{color: theme.textMuted, fontSize: 12, fontWeight: 700, letterSpacing: '0.11em', textTransform: 'uppercase', lineHeight: 1.2}}>{children}</div>
);

const Stat = ({label, value, unit, theme, leftBorder = false}: {label: string; value: string; unit?: string; theme: Theme; leftBorder?: boolean}) => (
  <div style={{borderTop: `1px solid ${theme.border}`, borderLeft: leftBorder ? `1px solid ${theme.border}` : undefined, padding: '18px 0 12px 18px', minWidth: 0}}>
    <Label theme={theme}>{label}</Label>
    <div style={{marginTop: 9, color: theme.text, fontSize: 28, fontWeight: 590, lineHeight: 1.05, letterSpacing: '-0.025em', fontVariantNumeric: 'tabular-nums'}}>
      {value}{unit ? <span style={{marginLeft: 7, color: theme.textMuted, fontSize: 13, fontWeight: 650}}>{unit}</span> : null}
    </div>
  </div>
);

export const TelemetryPanel = ({spec, point, progress, theme, vertical}: Props) => {
  const {t, number, date} = createI18n(spec.locale);
  const staticSummary = spec.outputMode === 'static-summary';
  const numericMean = (values: Array<number | null>) => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? valid.reduce((total, value) => total + value, 0) / valid.length : 0;
  };
  const numericMax = (values: Array<number | null>) => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? Math.max(...valid) : 0;
  };
  const numericMin = (values: Array<number | null>) => {
    const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
    return valid.length > 0 ? Math.min(...valid) : 0;
  };
  const speedSeries = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.speed3MinKmh), [spec.points]);
  const heartRateSeries = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.heartRateBpm), [spec.points]);
  const speed = staticSummary
    ? numericMean(spec.points.map((telemetryPoint) => telemetryPoint.speedKmh))
    : point.speed3MinKmh ?? point.speedKmh ?? 0;
  const heartRate = staticSummary ? numericMean(heartRateSeries) : point.heartRateBpm;
  const altitudeProfile = useMemo(() => spec.points.map((telemetryPoint) => telemetryPoint.altitudeM), [spec.points]);
  const runningAscentM = point.cumulativeElevationGainM;
  const ascentValue =
    !staticSummary && runningAscentM !== null && runningAscentM !== undefined
      ? Math.round(runningAscentM)
      : spec.summary.elevationGainM;
  const currentStats = [
      {label: t('distance'), value: number(point.distanceKm ?? 0, 1), unit: 'km'},
      {label: t('altitude'), value: number(point.altitudeM ?? 0), unit: 'm'},
      {label: t('grade'), value: number(point.gradePct ?? 0, 1), unit: '%'},
      {label: t('temperature'), value: number(point.temperatureC ?? 0, 1), unit: '°C'},
      point.powerWatts !== null
        ? {label: t('power'), value: number(point.powerWatts), unit: 'W'}
        : {label: t('ascent'), value: number(ascentValue), unit: 'm'},
      {label: t('totalTime'), value: elapsed(point.elapsedSeconds), unit: 'h'},
    ];
  const summaryStats = [
      {label: t('distance'), value: number(spec.summary.distanceKm, 1), unit: 'km'},
      {label: t('maximumAltitude'), value: number(numericMax(altitudeProfile)), unit: 'm'},
      {label: t('maximumGrade'), value: number(numericMax(spec.points.map((telemetryPoint) => telemetryPoint.gradePct)), 1), unit: '%'},
      {label: t('averageTemperature'), value: number(numericMean(spec.points.map((telemetryPoint) => telemetryPoint.temperatureC)), 1), unit: '°C'},
      spec.points.some((telemetryPoint) => telemetryPoint.powerWatts !== null)
        ? {label: t('averagePower'), value: number(numericMean(spec.points.map((telemetryPoint) => telemetryPoint.powerWatts))), unit: 'W'}
        : {label: t('ascent'), value: number(spec.summary.elevationGainM), unit: 'm'},
      {label: t('totalTime'), value: elapsed(spec.summary.sourceDurationSeconds), unit: 'h'},
    ];
  const stats = staticSummary ? summaryStats : currentStats;

  const header = (
    <div style={{display: 'flex', justifyContent: 'space-between', gap: 20, paddingBottom: vertical ? 18 : 26}}>
      <div style={{minWidth: 0}}>
        {spec.activity.title ? (
          <div style={{fontSize: vertical ? 31 : 34, fontWeight: 650, lineHeight: 1.08, letterSpacing: '-0.035em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{spec.activity.title}</div>
        ) : null}
        <div style={{fontSize: 15, color: theme.textSecondary, marginTop: spec.activity.title ? 8 : 0, lineHeight: 1.3}}>
          {spec.activity.date ? `${date(spec.activity.date)} · ` : ''}{number(spec.summary.distanceKm, 1)} km · +{number(spec.summary.elevationGainM)} m
        </div>
      </div>
    </div>
  );

  const speedBlock = (
    <div style={{borderTop: `1px solid ${theme.border}`, padding: vertical ? '18px 18px 12px 0' : '22px 0 18px'}}>
      <Label theme={theme}>{staticSummary ? t('averageSpeed') : t('speed')}</Label>
      <div style={{display: 'grid', gridTemplateColumns: vertical ? '0.9fr 1.1fr' : '0.85fr 1.15fr', gap: 18, alignItems: 'end', marginTop: 10}}>
        <div style={{fontSize: vertical ? 48 : 54, fontWeight: 590, lineHeight: 1, letterSpacing: '-0.045em', fontVariantNumeric: 'tabular-nums'}}>
          {number(speed, 1)}<span style={{fontSize: 15, color: theme.textMuted, marginLeft: 9, letterSpacing: 0}}>km/h</span>
        </div>
        <ProgressAxisChart
          values={speedSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.route}
          muted={theme.border}
          height={vertical ? 76 : 82}
        />
      </div>
    </div>
  );

  const heartBlock = heartRate !== null ? (
    <div style={{borderTop: `1px solid ${theme.border}`, borderLeft: vertical ? `1px solid ${theme.border}` : undefined, padding: vertical ? '18px 0 12px 18px' : '18px 0 16px'}}>
      <Label theme={theme}>{staticSummary ? t('averageHeartRate') : t('heartRate')}</Label>
      <div style={{display: 'grid', gridTemplateColumns: '0.78fr 1.22fr', gap: 18, alignItems: 'end', marginTop: 8}}>
        <div style={{fontSize: vertical ? 40 : 44, fontWeight: 590, lineHeight: 1, letterSpacing: '-0.04em', fontVariantNumeric: 'tabular-nums'}}>
          {number(heartRate)}<span style={{fontSize: 14, color: theme.textMuted, marginLeft: 8, letterSpacing: 0}}>bpm</span>
        </div>
        <ProgressAxisChart
          values={heartRateSeries}
          progress={progress}
          stroke={theme.border}
          completed={theme.textSecondary}
          highlight={theme.heartRate}
          muted={theme.border}
          height={vertical ? 76 : 82}
        />
      </div>
    </div>
  ) : null;

  return (
    <div style={{height: '100%', boxSizing: 'border-box', padding: vertical ? '26px 42px 24px' : '42px 36px 28px', display: 'flex', flexDirection: 'column', color: theme.text}}>
      {header}
      <div style={vertical ? {display: 'grid', gridTemplateColumns: '1fr 1fr'} : undefined}>
        {speedBlock}
        {heartBlock}
      </div>
      <div style={{display: 'grid', gridTemplateColumns: vertical ? 'repeat(6, 1fr)' : '1fr 1fr'}}>
        {stats.map((stat, statIndex) => (
          <Stat key={stat.label} {...stat} theme={theme} leftBorder={vertical ? statIndex > 0 : statIndex % 2 === 1} />
        ))}
      </div>
      <div style={{borderTop: `1px solid ${theme.border}`, padding: vertical ? '16px 0 10px' : '18px 0 12px', flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: vertical ? '150px 1fr' : '1fr', gap: 22, alignItems: 'center'}}>
        <div>
          <Label theme={theme}>{t('elevationProfile')}</Label>
          <div style={{marginTop: 9, color: theme.text, fontSize: vertical ? 29 : 27, fontWeight: 590, fontVariantNumeric: 'tabular-nums'}}>
            {staticSummary
              ? `${number(numericMin(altitudeProfile))}—${number(numericMax(altitudeProfile))}`
              : number(point.altitudeM ?? 0)}
            <span style={{marginLeft: 7, color: theme.textMuted, fontSize: 13}}>m</span>
          </div>
        </div>
        <ProgressAxisChart
          values={altitudeProfile}
          progress={progress}
          stroke={theme.textMuted}
          completed={theme.textSecondary}
          highlight={theme.route}
          muted={theme.border}
          height={vertical ? 210 : 135}
        />
      </div>
      <div style={{paddingTop: 18}}>
        {spec.show_progress_bar !== false ? (
          <>
            <div style={{display: 'flex', justifyContent: 'space-between', color: theme.textMuted, fontSize: 11, fontWeight: 700, letterSpacing: '0.11em', textTransform: 'uppercase', marginBottom: 10}}>
              <span>{t('progress')}</span><span>{Math.round(progress * 100)}%</span>
            </div>
            <div style={{height: 2, background: theme.border}}><div style={{height: '100%', width: `${progress * 100}%`, background: theme.route}} /></div>
          </>
        ) : null}
      </div>
    </div>
  );
};
