"""bromigOS's adapters (registered on import). Third-party adapters: registry.py."""
from . import infra, kube, media, misc, models, prometheus, voice  # noqa: F401  (each registers its adapters)
# the lab's own services (docs/homelab.md, "Adapters"): gpus, logs, edge, storage, games, media library, AI, CI, backups
from . import labai, labbackup, labci, labedge, labenergy, labgames, labgpu, labmedia, labobserve, labstorage  # noqa: F401
from . import labrequests  # noqa: F401  (Seerr and the download clients: the requests capability)
from . import labcards  # noqa: F401  (their console cards, when the console is installed)
