/** Hold numeric readouts in video time, independent of route easing or source length. */
export const readoutFrame = (
  frame: number,
  fps: number,
  animationFrames: number,
  intervalSeconds = 0.3,
): number => {
  if (frame >= animationFrames) return animationFrames;
  const intervalFrames = Math.max(1, Math.round(intervalSeconds * fps));
  return Math.floor(Math.max(0, frame) / intervalFrames) * intervalFrames;
};
