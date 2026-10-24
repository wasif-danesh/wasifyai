"""The training engine of the desktop profile (ADR-0073).

Today it is the product's preview trainer: it runs the same steps and writes sample pictures that
say "Preview", and it learns nothing (the screens say so). The real trainer (mflux on the Mac, then
Unsloth's component) replaces it here, with the same interface, when it is installed."""

from typing import Any


def preview_trainer() -> Any:
    """The preview trainer, or None when the training product is not part of this build."""
    try:
        from wasifyai_training.trainer import PreviewTrainer
    except ImportError:
        return None
    return PreviewTrainer()
