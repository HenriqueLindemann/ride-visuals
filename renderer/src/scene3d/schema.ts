import {z} from 'zod';

/**
 * Contract for the 3D scenes (flyover, stretch, strata), written by
 * `src/ride_visuals/scene3d/spec.py`. The Python "director" owns the timing:
 * it sends the camera and every animated scalar ("channel") as one value per
 * frame, so the renderer is a deterministic player and the choreography can be
 * tested without a browser.
 */

const series = z.array(z.number());

export const encodedTrackSchema = z.object({
  x: z.array(z.number()),
  y: z.array(z.number()),
  d: z.array(z.number()),
  a: z.array(z.number()).nullable().optional(),
});

export const sceneSpecSchema = z.object({
  schemaVersion: z.literal('1.0'),
  kind: z.enum(['flyover', 'stretch', 'strata']),
  locale: z.enum(['en', 'pt-BR']),
  look: z.enum(['carbon', 'satellite']),
  profile: z.object({
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().int().positive(),
    durationInFrames: z.number().int().positive(),
  }),
  tiles: z.object({
    dem: z.string(),
    vector: z.string(),
    satellite: z.string().nullable(),
    demMaxZoom: z.number().int(),
    vectorMaxZoom: z.number().int(),
    satelliteMaxZoom: z.number().int(),
  }),
  /** Short data credit drawn on screen; null keeps the frame clean. */
  credits: z.string().nullable(),
  camera: z.object({
    lon: series,
    lat: series,
    zoom: series,
    pitch: series,
    bearing: series,
    /** Height of the camera's centre point, exaggerated metres. */
    elevation: series,
    /** Terrain exaggeration (0 = flat map). */
    terrain: series,
    /** 1 renders the globe, 0 Web Mercator. */
    globe: series,
    mapOpacity: series,
    contours: series,
    /** Satellite imagery mix over the carbon map (satellite look only). */
    satellite: series,
    /** Hillshade contrast multiplier; older specs omit it (1). */
    shade: series.optional(),
  }),
  channels: z.record(z.string(), series),
  tracks: z.array(encodedTrackSchema),
  /** Kind-specific facts (labels, stats, plates...), interpreted by each score. */
  story: z.record(z.string(), z.unknown()),
});

export type SceneSpec = z.infer<typeof sceneSpecSchema>;

/** Composition props: the (large) spec is fetched once per tab, not serialised per frame. */
export const sceneInputSchema = z.object({
  specUrl: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  fps: z.number().int().positive(),
  durationInFrames: z.number().int().positive(),
});

export type SceneInput = z.infer<typeof sceneInputSchema>;
