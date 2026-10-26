/**
 * Edge darkening under the drawn lines and the text: the land grows darker
 * towards a frame edge that carries text, transparent through the middle.
 * No box, no edge of its own: only the land behind the text recedes. Each edge
 * falls off along a smooth curve, so no band shows where it ends; `strength`
 * scales the darkest point, for scenes whose land is the picture.
 *
 * `far` is the distance: the top of the frame sinking into the dark, to hold
 * back where the map stops drawing detail. It depends on the screen alone, so
 * nothing about it moves with the map's zoom steps.
 */
const TOP_REACH = 0.34;
const BOTTOM_REACH = 0.3;
const FAR_REACH = 0.5;

const falloff = (alpha: number, reach: number, edge: 'top' | 'bottom', power = 2) => {
  const stops: string[] = [];
  for (let i = 0; i <= 8; i++) {
    const u = i / 8;
    const k = (1 - u * u * (3 - 2 * u)) ** power;
    const at = edge === 'top' ? u * reach : 1 - reach + (1 - u) * reach;
    stops.push(`rgba(0,0,0,${(alpha * k).toFixed(3)}) ${(at * 100).toFixed(1)}%`);
  }
  return edge === 'top' ? stops : stops.reverse();
};

const gradient = (stops: string[]) => `linear-gradient(to bottom, ${stops.join(', ')})`;

export const Scrim = ({top = 0, bottom = 0, strength = 1, far = 0}: {top?: number; bottom?: number; strength?: number; far?: number}) => {
  if (top <= 0.004 && bottom <= 0.004 && far <= 0.004) return null;
  const layers = [];
  if (far > 0.004) layers.push(gradient(falloff(far, FAR_REACH, 'top', 1)));
  layers.push(gradient([...falloff(0.62 * strength * top, TOP_REACH, 'top'), ...falloff(0.5 * strength * bottom, BOTTOM_REACH, 'bottom')]));
  return <div style={{position: 'absolute', inset: 0, background: layers.join(', ')}} />;
};
