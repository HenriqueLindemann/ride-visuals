/**
 * Edge darkening under the drawn lines and the text: the land grows darker
 * towards a frame edge that carries text, transparent through the middle.
 * No box, no edge of its own: only the land behind the text recedes.
 */
export const Scrim = ({top = 0, bottom = 0}: {top?: number; bottom?: number}) =>
  top > 0.004 || bottom > 0.004 ? (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: `linear-gradient(to bottom, rgba(0,0,0,${(0.62 * top).toFixed(3)}) 0%, rgba(0,0,0,${(0.3 * top).toFixed(3)}) 16%, rgba(0,0,0,0) 34%, rgba(0,0,0,0) 70%, rgba(0,0,0,${(0.5 * bottom).toFixed(3)}) 100%)`,
      }}
    />
  ) : null;
