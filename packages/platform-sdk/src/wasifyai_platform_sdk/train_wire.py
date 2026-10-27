# ruff: noqa: E501
"""The wire format of training jobs (ADR-0073 amendment 2026-10-27, `docs/train-web-plan.md`): the API's remote trainers and the
worker's handlers share these names. Pictures, clips and the adapter a run leaves are files in object storage; the numbers are `meta`.

A worker that can teach a family lists it as a component (`train.video`, ...) with `ready`, `problem`, `fit`, `preflight` and `state`."""

VIDEO = "train.video"  # media in (`m0`, `m1`, ...), the adapter out (`adapter`); params: items, job
IMAGE = "train.image"  # pictures in (`p0.png`, ...), the adapter out (`adapter`) and the sample pictures (`samples/<name>`)
IMAGE_TOKENIZE = (
    "train.image.tokenize"  # words in, how the picture model's tokenizer splits each (`meta.words`)
)
DECISION = "train.decision"  # no files in; the model's files out (`model/<name>`); params: question, rows, base
DECISION_ANSWER = "train.decision.answer"  # texts in (params), answers out (`meta.answers`); a taught model or a base
WRITING = "train.writing"  # no files in; the adapter out (`adapter/<name>`); params: records, steps, questions, base
WRITING_ANSWER = (
    "train.writing.answer"  # an adapter in (`a/<name>`, optional), answers out (`meta.answers`)
)
KINDS = [VIDEO, IMAGE, IMAGE_TOKENIZE, DECISION, DECISION_ANSWER, WRITING, WRITING_ANSWER]
COMPONENT_VIDEO = "train.video"  # the key of a worker's `components` entry
COMPONENT_IMAGE = "train.image"
COMPONENT_DECISION = "train.decision"
COMPONENT_WRITING = "train.writing"
COMPONENTS = {
    VIDEO: COMPONENT_VIDEO,
    IMAGE: COMPONENT_IMAGE,
    IMAGE_TOKENIZE: COMPONENT_IMAGE,
    DECISION: COMPONENT_DECISION,
    DECISION_ANSWER: COMPONENT_DECISION,
    WRITING: COMPONENT_WRITING,
    WRITING_ANSWER: COMPONENT_WRITING,
}
