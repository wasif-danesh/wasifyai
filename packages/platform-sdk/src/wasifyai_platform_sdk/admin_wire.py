"""The wire format of the jobs an admin starts on a worker (ADR-0087, stage P5): getting a model
onto the machine that runs the worker, or setting up a component. They carry no files; the answer is
how it went, and the progress is read while it runs."""

FETCH_MODEL = "admin.fetch_model"  # params `model_id`; the model's files are downloaded and checked
FETCH_ENGINE = "admin.fetch_engine"  # params `name`: a component of the speech runtime to set up
KINDS = [FETCH_MODEL, FETCH_ENGINE]
ENGINES = [
    "lipsync-engine",
    "video-trainer",
    "image-trainer",
    "decision-trainer",
    "writing-trainer",
]  # the names FETCH_ENGINE accepts
LIPSYNC_COMPONENT = "lipsync_engine"  # the key of a worker's `components` entry for it
VIDEO_TRAINER = "video-trainer"  # the video trainer's set-up (a component of `train.video`)
DECISION_TRAINER = (
    "decision-trainer"  # the decision trainer's set-up (a component of `train.decision`)
)
WRITING_TRAINER = "writing-trainer"  # the writing trainer's set-up (a component of `train.writing`)
IMAGE_TRAINER = "image-trainer"  # the picture trainer's set-up (a component of `train.image`)
