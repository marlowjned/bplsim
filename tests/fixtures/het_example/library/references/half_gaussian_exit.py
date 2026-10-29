from math import exp

from bplsim.measure import Slot, reference
from bplsim.units import FluxDensity, G


@reference(version="1.0.0", kind="line[B]")
def half_gaussian_exit(design, z, channel: Slot = Slot("channel", type="het:part_types/channel_insulator"),
                       sigma_per_length: float = 0.353, peak: FluxDensity = 165 * G):
    """Target supplied 2026-10-21 (TARGET_REPORT.md): B_r is a half-Gaussian peaked at the exit plane,
    sigma = 0.353 x channel length. Defined inside the channel only (anode face to exit plane)."""
    depth = design.parts[channel].depth
    sigma = sigma_per_length * depth
    return {"B_r": [peak * exp(-0.5 * (zi / sigma) ** 2) if -depth - 1e-12 <= zi <= 1e-12 else None for zi in z]}
