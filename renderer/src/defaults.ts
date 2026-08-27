import type {ActivityRenderSpec} from './schema';

export const defaultActivitySpec: ActivityRenderSpec = {
  schemaVersion: '1.0',
  kind: 'activity-telemetry',
  outputMode: 'animated',
  locale: 'en',
  theme: 'midnight',
  show_progress_bar: false,
  profile: {width: 1920, height: 1080, fps: 30, duration_seconds: 5, hold_seconds: 1},
  activity: {id: 'preview', title: 'Morning Ride', date: '2024-08-23T08:00:00Z'},
  background: null,
  summary: {distanceKm: 42.6, elevationGainM: 620, sourceDurationSeconds: 7200, sourcePointCount: 4, renderPointCount: 4, speedWindowSeconds: 180},
  points: [
    {elapsedSeconds: 0, lat: 10.0, lon: 20.0, altitudeM: 250, distanceKm: 0, speedKmh: 20, speed3MinKmh: 20, heartRateBpm: 112, powerWatts: null, temperatureC: 19, gradePct: 0, bearingDeg: 0},
    {elapsedSeconds: 2400, lat: 10.06, lon: 20.06, altitudeM: 410, distanceKm: 14.2, speedKmh: 26, speed3MinKmh: 24, heartRateBpm: 136, powerWatts: null, temperatureC: 20, gradePct: 4, bearingDeg: 35},
    {elapsedSeconds: 4800, lat: 10.02, lon: 20.14, altitudeM: 330, distanceKm: 28.4, speedKmh: 31, speed3MinKmh: 27, heartRateBpm: 148, powerWatts: null, temperatureC: 21, gradePct: -2, bearingDeg: 120},
    {elapsedSeconds: 7200, lat: 10.0, lon: 20.0, altitudeM: 250, distanceKm: 42.6, speedKmh: 22, speed3MinKmh: 23, heartRateBpm: 130, powerWatts: null, temperatureC: 22, gradePct: 0, bearingDeg: 220},
  ],
};
