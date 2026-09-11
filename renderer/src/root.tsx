import {Composition, type CalculateMetadataFunction} from 'remotion';
import {ActivityTelemetry} from './compositions/ActivityTelemetry';
import {ActivityOverlay} from './compositions/ActivityOverlay';
import {RouteOverlay, StatsOverlay} from './compositions/MinimalOverlays';
import {ActivityClean} from './compositions/ActivityClean';
import {ActivityMinimal, ActivityMinimalOverlay} from './compositions/ActivityMinimal';
import {defaultActivitySpec} from './defaults';
import {activityRenderSpecSchema, type ActivityRenderSpec} from './schema';

const calculateMetadata: CalculateMetadataFunction<ActivityRenderSpec> = ({props}) => ({
  width: props.profile.width,
  height: props.profile.height,
  fps: props.profile.fps,
  durationInFrames: Math.round((props.profile.duration_seconds + props.profile.hold_seconds) * props.profile.fps),
  props,
});

export const RideVisualsRoot = () => (
  <>
    {[{id: 'RouteOverlay', component: RouteOverlay}, {id: 'StatsOverlay', component: StatsOverlay},
      {id: 'ActivityMinimalOverlay', component: ActivityMinimalOverlay}].map(({id, component}) => (
      <Composition key={id} id={id} component={component} durationInFrames={180} fps={30}
        width={960} height={320} defaultProps={defaultActivitySpec}
        calculateMetadata={calculateMetadata} schema={activityRenderSpecSchema} />
    ))}
    <Composition
      id="ActivityTelemetry"
      component={ActivityTelemetry}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={defaultActivitySpec}
      calculateMetadata={calculateMetadata}
      schema={activityRenderSpecSchema}
    />
    <Composition
      id="ActivityClean"
      component={ActivityClean}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={defaultActivitySpec}
      calculateMetadata={calculateMetadata}
      schema={activityRenderSpecSchema}
    />
    <Composition
      id="ActivityMinimal"
      component={ActivityMinimal}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={defaultActivitySpec}
      calculateMetadata={calculateMetadata}
      schema={activityRenderSpecSchema}
    />
    <Composition
      id="ActivityOverlay"
      component={ActivityOverlay}
      durationInFrames={180}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{
        ...defaultActivitySpec,
        profile: {...defaultActivitySpec.profile, width: 1080, height: 1920},
      }}
      calculateMetadata={calculateMetadata}
      schema={activityRenderSpecSchema}
    />
  </>
);
