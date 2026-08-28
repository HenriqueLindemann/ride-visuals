import {ActivityLayout} from '../components/ActivityLayout';
import type {ActivityRenderSpec} from '../schema';

/** Transparent, framed telemetry overlay sharing the exact ActivityTelemetry geometry. */
export const ActivityOverlay = (props: ActivityRenderSpec) => <ActivityLayout spec={props} variant="overlay" />;
