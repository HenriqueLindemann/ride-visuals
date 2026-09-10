import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {readoutFrame} from './readout';
import {pointAtProgress} from './telemetry';
import type {ActivityRenderSpec, TelemetryPoint} from '../schema';

/** Smoothstep timeline + damped numeric readouts, shared by every composition. */
export const useActivityTimeline = (spec: ActivityRenderSpec, readoutIntervalSeconds?: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const animationFrames = Math.round(spec.profile.duration_seconds * fps);
  const linear = interpolate(frame, [0, animationFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const progress = linear * linear * (3 - 2 * linear);
  const index = pointAtProgress(spec.points, progress, spec.summary.sourceDurationSeconds);
  // Numbers tick in ~0.2%-of-route steps so they stay readable.
  const readoutStep = 0.2 / spec.profile.duration_seconds;
  const readoutLinear = readoutFrame(frame, fps, animationFrames, readoutIntervalSeconds) / animationFrames;
  const steppedProgress = readoutIntervalSeconds === undefined
    ? (progress > 1 - readoutStep ? 1 : Math.floor(progress / readoutStep) * readoutStep)
    : readoutLinear * readoutLinear * (3 - 2 * readoutLinear);
  const point: TelemetryPoint =
    spec.points[pointAtProgress(spec.points, steppedProgress, spec.summary.sourceDurationSeconds)];
  return {progress, index, point};
};

