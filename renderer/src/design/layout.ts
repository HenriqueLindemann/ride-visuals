/**
 * Canonical telemetry geometry. Every composition reads the split from here so
 * the map/panel relationship cannot drift between variants or aspect ratios.
 *
 * `src/ride_visuals/video/activity_basemap.py` mirrors these values to render
 * georeferenced basemap tiles — keep both sides in sync.
 */
export const PANEL_SHARE_LANDSCAPE = 0.3; // 16:9 → panel is the right 30%
export const MAP_SHARE_PORTRAIT = 0.5; // 9:16 → map is the top half
export const INSTAGRAM_PANEL_SHARE = 0.36;
export const INSTAGRAM_PROFILE_SAFE_PX = 220;
export const INSTAGRAM_REPLY_SAFE_PX = 220;

export const landscapeSafeInsets = (presentation: string) =>
  presentation === 'instagram-story-landscape'
    ? {left: INSTAGRAM_PROFILE_SAFE_PX, right: INSTAGRAM_REPLY_SAFE_PX}
    : {left: 0, right: 0};

/** RouteMap inner breathing room, shared by every composition. */
export const mapPadding = (vertical: boolean, scale: number) =>
  Math.round((vertical ? 56 : 64) * scale);

export const FONT_FAMILY =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
