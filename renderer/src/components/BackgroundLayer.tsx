import type {CSSProperties} from 'react';
import {Img, OffthreadVideo, staticFile} from 'remotion';
import {landscapeSafeInsets} from '../design/layout';
import type {ActivityRenderSpec} from '../schema';

type Background = ActivityRenderSpec['background'];

export const BackgroundLayer = ({
  background,
  presentation = 'standard',
}: {
  background: Background;
  presentation?: ActivityRenderSpec['presentation'];
}) => {
  if (!background) {
    return null;
  }

  // Scale slightly so a CSS blur never exposes transparent canvas edges.
  const scale = 1 + background.blur_px / 500;
  const safeInsets = landscapeSafeInsets(presentation);
  const mediaStyle: CSSProperties = {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    transform: `scale(${scale})`,
    filter: background.blur_px > 0 ? `blur(${background.blur_px}px)` : undefined,
  };

  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
      {background.kind === 'video' ? (
        // Frame-accurate extraction, always muted: the deliverable audio is
        // muxed from the source clip by the Python engine. The clip is
        // validated up front to cover the whole composition, so no loop is
        // needed here.
        <OffthreadVideo src={staticFile(background.src)} muted style={mediaStyle} />
      ) : (
        <Img src={background.src} style={mediaStyle} />
      )}
      <div style={{position: 'absolute', inset: 0, background: `rgba(3, 6, 11, ${background.dim})`}} />
      {background.attribution ? (
        <div
          style={{
            position: 'absolute',
            left: safeInsets.left + 8,
            bottom: background.attribution_bottom_px,
            // Only `left` is set so the label shrinks to fit its text; the
            // maxWidth keeps the pill inside the safe content area.
            maxWidth: `calc(100% - ${safeInsets.left + safeInsets.right + 16}px)`,
            padding: '2px 5px',
            color: 'rgba(255, 255, 255, 0.82)',
            background: 'rgba(0, 0, 0, 0.62)',
            fontSize: 10,
            lineHeight: 1.2,
            letterSpacing: '0.01em',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {background.attribution}
        </div>
      ) : null}
    </div>
  );
};
