from . import classic, ict, sessions  # noqa: F401 — enregistre les features
from .registry import REGISTRY, FeatureCache, validate_params  # noqa: F401
from ..regime import engine as _regime  # noqa: F401,E402 — régimes exposés comme feature
