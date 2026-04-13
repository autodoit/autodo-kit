"""在线检索执行层。"""

from .content_portal_cnki import (
    execute_cnki_metadata,
    execute_cnki_single_download,
    execute_cnki_single_structured,
)
from .content_portal_spis import (
    execute_spis_metadata,
    execute_spis_single_download,
    execute_spis_single_structured,
)
from .navigation_portal import (
    execute_navigation_catalog,
    execute_navigation_retry,
)
from .open_platform import (
    execute_open_metadata,
    execute_open_single_download,
    execute_open_single_structured,
)

__all__ = [
    "execute_cnki_metadata",
    "execute_cnki_single_download",
    "execute_cnki_single_structured",
    "execute_spis_metadata",
    "execute_spis_single_download",
    "execute_spis_single_structured",
    "execute_navigation_catalog",
    "execute_navigation_retry",
    "execute_open_metadata",
    "execute_open_single_download",
    "execute_open_single_structured",
]
