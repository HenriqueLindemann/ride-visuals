import {ActivityLayout} from '../components/ActivityLayout';
import type {ActivityRenderSpec} from '../schema';

/** Full-bleed telemetry video: 70/30 map/panel in landscape, 65/35 in portrait. */
export const ActivityTelemetry = (props: ActivityRenderSpec) => <ActivityLayout spec={props} />;
