import {Img} from 'remotion';
import type {ActivityRenderSpec} from '../schema';

type Background = ActivityRenderSpec['background'];

export const BackgroundLayer = ({background}: {background: Background}) => {
  if (!background) {
    return null;
  }

  // Scale slightly so a CSS blur never exposes transparent canvas edges.
  const scale = 1 + background.blur_px / 500;
  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
      <Img
        src={background.src}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          transform: `scale(${scale})`,
          filter: background.blur_px > 0 ? `blur(${background.blur_px}px)` : undefined,
        }}
      />
      <div style={{position: 'absolute', inset: 0, background: `rgba(3, 6, 11, ${background.dim})`}} />
      {background.attribution ? (
        <div
          style={{
            position: 'absolute',
            left: 8,
            bottom: 6,
            maxWidth: 'calc(100% - 16px)',
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
