// Compositions known to the Remotion bundle (`frontend/remotion/render.mjs`).
import { Composition, type CalculateMetadataFunction } from "remotion";
import { DUB_FPS, DubSubtitles, type DubSubtitlesProps } from "./DubSubtitles";

const DEFAULT_PROPS: DubSubtitlesProps = {
  src: "", width: 1080, height: 1920, fps: DUB_FPS, durationS: 10, cues: [],
  layout: { x: 0.5, y: 0.8, scale: 1, blur: null }, style: "rm_box",
};

// the video decides the frame: size, fps and length come in as props
const calculateMetadata: CalculateMetadataFunction<DubSubtitlesProps> = ({ props }) => ({
  width: Math.max(2, Math.round(props.width / 2) * 2),
  height: Math.max(2, Math.round(props.height / 2) * 2),
  fps: props.fps || DUB_FPS,
  durationInFrames: Math.max(1, Math.ceil(props.durationS * (props.fps || DUB_FPS))),
});

export const RemotionRoot: React.FC = () => (
  <Composition
    id="DubSubtitles"
    component={DubSubtitles}
    width={DEFAULT_PROPS.width}
    height={DEFAULT_PROPS.height}
    fps={DEFAULT_PROPS.fps}
    durationInFrames={Math.ceil(DEFAULT_PROPS.durationS * DEFAULT_PROPS.fps)}
    defaultProps={DEFAULT_PROPS}
    calculateMetadata={calculateMetadata}
  />
);
