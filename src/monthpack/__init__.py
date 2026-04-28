"""monthpack package."""

from monthpack.config import write_dataframe_config
from monthpack.config import write_pickle_config
from monthpack.config import write_series_config
from monthpack.manager import SourceManager
from monthpack.period import Period
from monthpack.source import Metadata
from monthpack.source import Source

__all__ = [
    "Metadata",
    "Period",
    "Source",
    "SourceManager",
    "write_dataframe_config",
    "write_pickle_config",
    "write_series_config",
    "__version__",
]

__version__ = "0.2.2"
