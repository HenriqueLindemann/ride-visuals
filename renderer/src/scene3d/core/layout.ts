/**
 * Instagram Story safe area at 1080x1920 (px at scale 1): the profile row on
 * top and the reply bar below cover this much, so portrait text stays inside.
 * Mirrors INSTAGRAM_STORY in ride_visuals/video/instagram.py.
 */
export const STORY_SAFE_TOP = 220;
export const STORY_SAFE_BOTTOM = 220;

/** Height of a metric block (px at scale 1): its label line, the gap, the value line (see Typography). */
export const metricHeight = (size: number) => 17 + 10 + size;
