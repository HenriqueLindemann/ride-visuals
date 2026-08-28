import {useLayoutEffect, useRef, useState} from 'react';
import {continueRender, delayRender} from 'remotion';
import type {RefObject} from 'react';

export type Size = {width: number; height: number};

/**
 * Measures an element's content box and keeps the value in sync (including
 * live resizes in the Remotion Player preview).
 *
 * Charts render nothing until the first measurement lands, so during Remotion
 * rendering we hold a `delayRender` handle while unmeasured: a freshly mounted
 * page (each concurrency chunk, or an internal page restart) can never be
 * captured with empty charts — the capture waits for the measurement instead.
 * This is the same pattern Remotion's own <Img> uses while an image loads.
 */
export const useElementSize = <T extends HTMLElement>(): [RefObject<T | null>, Size] => {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<Size>({width: 0, height: 0});
  const delayHandle = useRef<number | null>(null);
  if ((size.width <= 0 || size.height <= 0) && delayHandle.current === null) {
    delayHandle.current = delayRender('measuring element size');
  }

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const {width, height} = element.getBoundingClientRect();
      // Browser page setup can briefly report a zero width or height. Keeping
      // the last usable box prevents an already-rendered SVG from blinking
      // out during that transient layout pass; on first mount the delay handle
      // remains pending until both dimensions are valid.
      if (width <= 0 || height <= 0) return;
      setSize((previous) =>
        Math.abs(previous.width - width) < 0.5 && Math.abs(previous.height - height) < 0.5
          ? previous
          : {width, height},
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
      // Never leave a dangling handle when unmounting before measuring.
      if (delayHandle.current !== null) {
        continueRender(delayHandle.current);
        delayHandle.current = null;
      }
    };
  }, []);

  useLayoutEffect(() => {
    // `measure()` only schedules the size state update. Releasing the render
    // handle in the same effect can let Remotion capture before React commits
    // the rerender containing the SVG (most visible on heavier portrait
    // frames). This effect runs after that commit. Waiting through two browser
    // animation frames also guarantees the committed drawing has reached a
    // paint before Remotion is allowed to capture it.
    if (size.width > 0 && size.height > 0 && delayHandle.current !== null) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (delayHandle.current !== null) {
            continueRender(delayHandle.current);
            delayHandle.current = null;
          }
        });
      });
    }
  }, [size.height, size.width]);

  return [ref, size];
};
