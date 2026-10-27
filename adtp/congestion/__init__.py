from .adtp_cc import AdtpController
from .base import CongestionController, LossDecision
from .fixed import FixedWindowController
from .reno import RenoController

CONTROLLERS = {
    "reno": RenoController,
    "adtp": AdtpController,
    "fixed": FixedWindowController,
}


def make_controller(name: str, **kwargs) -> CongestionController:
    try:
        return CONTROLLERS[name.lower()](**kwargs)
    except KeyError:
        raise ValueError(f"unknown controller '{name}', choose from {sorted(CONTROLLERS)}") from None


__all__ = [
    "AdtpController", "CongestionController", "FixedWindowController", "LossDecision",
    "RenoController", "CONTROLLERS", "make_controller",
]
