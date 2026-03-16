"""Cycle time distribution models for factory stations."""

from dataclasses import dataclass
from typing import Protocol
import numpy as np


class Distribution(Protocol):
    """Protocol for sampling from a distribution."""
    def sample(self, rng: np.random.Generator) -> float: ...


@dataclass
class NormalDistribution:
    mean: float  # minutes
    std: float   # minutes
    min_val: float = 0.0
    max_val: float = float('inf')

    def sample(self, rng: np.random.Generator) -> float:
        val = rng.normal(self.mean, self.std)
        return float(np.clip(val, self.min_val, self.max_val))


@dataclass
class LogNormalDistribution:
    mean: float  # minutes (of the underlying normal)
    std: float   # minutes
    min_val: float = 0.0
    max_val: float = float('inf')

    def sample(self, rng: np.random.Generator) -> float:
        # Convert mean/std of the lognormal to mu/sigma of underlying normal
        variance = self.std ** 2
        mu = np.log(self.mean ** 2 / np.sqrt(variance + self.mean ** 2))
        sigma = np.sqrt(np.log(1 + variance / self.mean ** 2))
        val = rng.lognormal(mu, sigma)
        return float(np.clip(val, self.min_val, self.max_val))


@dataclass
class FixedRateDistribution:
    """For continuous-feed stations like saws and CNC."""
    units_per_hour: float

    def sample(self, rng: np.random.Generator) -> float:
        # Returns minutes per unit
        return 60.0 / self.units_per_hour


@dataclass
class FixedDistribution:
    value: float  # minutes

    def sample(self, rng: np.random.Generator) -> float:
        return self.value
