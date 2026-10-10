"""Ominvox - live local audio translation with per-speaker voice matching."""
__version__ = "0.1.0"

# Silence pyannote's torchcodec "could not load libtorchcodec" warning. It is
# harmless here: we always hand pyannote in-memory {"waveform","sample_rate"}
# dicts, so its torchcodec file-decoder path is never exercised. Filtering by
# the emitting module is robust (the message itself starts with a newline).
import warnings as _warnings
_warnings.filterwarnings(
    "ignore", category=UserWarning, module=r"pyannote\.audio\.core\.io"
)
