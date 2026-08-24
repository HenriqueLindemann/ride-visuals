import {z} from 'zod';

export const telemetryPointSchema = z.object({
  elapsedSeconds: z.number(),
  lat: z.number(),
  lon: z.number(),
  altitudeM: z.number().nullable(),
  distanceKm: z.number().nullable(),
  speedKmh: z.number().nullable(),
  speed3MinKmh: z.number().nullable(),
  heartRateBpm: z.number().nullable(),
  powerWatts: z.number().nullable(),
  temperatureC: z.number().nullable(),
  gradePct: z.number().nullable(),
  bearingDeg: z.number().nullable(),
});

export const activityRenderSpecSchema = z.object({
  schemaVersion: z.literal('1.0'),
  kind: z.literal('activity-telemetry'),
  outputMode: z.enum(['animated', 'static-summary']).default('animated'),
  locale: z.enum(['en', 'pt-BR']),
  theme: z.enum(['midnight', 'frost']),
  profile: z.object({
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().int().positive(),
    duration_seconds: z.number().positive(),
    hold_seconds: z.number().nonnegative(),
  }),
  activity: z.object({
    id: z.string(),
    title: z.string(),
    date: z.string().nullable(),
  }),
  background: z
    .object({
      src: z.string(),
      blur_px: z.number().min(0).max(100),
      dim: z.number().min(0).max(1),
      attribution: z.string().nullable().default(null),
    })
    .nullable(),
  summary: z.object({
    distanceKm: z.number(),
    elevationGainM: z.number(),
    sourceDurationSeconds: z.number().nonnegative(),
    sourcePointCount: z.number().nonnegative(),
    renderPointCount: z.number().nonnegative(),
    speedWindowSeconds: z.number().positive(),
  }),
  points: z.array(telemetryPointSchema).min(2),
});

export type TelemetryPoint = z.infer<typeof telemetryPointSchema>;
export type ActivityRenderSpec = z.infer<typeof activityRenderSpecSchema>;
