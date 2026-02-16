"""Analysis modules: EV bridge, multiples, growth, operating metrics."""

from .enterprise_value import build_ev_bridge
from .growth import compute_growth
from .multiples import compute_multiples
from .operating import compute_operating

__all__ = ["build_ev_bridge", "compute_growth", "compute_multiples", "compute_operating"]
