"""monthpack package."""

from monthpack.config_templates import write_sample_config
from monthpack.period import Period
from monthpack.source import Metadata
from monthpack.source import Source

__all__ = [
    "Metadata",
    "Period",
    "Source",
    "write_sample_config",
    "__version__",
]

__version__ = "0.1.3"
