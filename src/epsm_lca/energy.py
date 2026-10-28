# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Supplied annual energy, tied to the building it describes; no engine execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from ._validation import number, text
from .settings import ENERGY_BOUNDARY


@dataclass(frozen=True, repr=False)
class AnnualEnergy:
    """Annual delivered energy with covered uses and an honest source.

    Parameters
    ----------
    state_id : str
        Core snapshot identity; use for_building to capture it.
    delivered_by_carrier : mapping
        Nonnegative annual kWh by carrier, including known zero values.
    source : str
        Measurement, engine output or stated assumption behind the numbers.
    boundary : str, optional
        Covered uses, defaulting to space heating and ventilation fans.
    hourly_by_carrier : mapping, optional
        8760 delivered kWh per hour for some or all carriers. Their sums must equal
        the annual values; time-varying factors and prices need them.

    Notes
    -----
    Recording a building identity does not verify the supplied numbers. No
    simulation is run. Amounts are copied and read-only.

    Examples
    --------
    >>> energy = AnnualEnergy('saved-state', {'electricity': 1000}, 'Teaching assumption')
    >>> energy.delivered_by_carrier['electricity']
    1000.0
    """

    state_id: str
    delivered_by_carrier: Mapping[str, float]
    source: str
    boundary: str = ENERGY_BOUNDARY
    hourly_by_carrier: Mapping[str, tuple[float, ...]] | None = None

    def __post_init__(self) -> None:
        for field in ("state_id", "source", "boundary"):
            text(getattr(self, field), field)
        if (
            not isinstance(self.delivered_by_carrier, Mapping)
            or not self.delivered_by_carrier
        ):
            raise ValueError("Supply annual delivered kWh by carrier")
        amounts = {
            text(k, "energy carrier"): number(v, f"{k}: annual kWh", nonnegative=True)
            for k, v in self.delivered_by_carrier.items()
        }
        object.__setattr__(self, "delivered_by_carrier", MappingProxyType(amounts))
        hourly = {}
        for carrier, values in dict(self.hourly_by_carrier or {}).items():
            if carrier not in amounts:
                raise ValueError(f"{carrier}: hourly values need an annual carrier total")
            series = tuple(number(v, f"{carrier}: hourly kWh", nonnegative=True) for v in values)
            if len(series) != 8760:
                raise ValueError(f"{carrier}: hourly delivered energy needs 8760 values")
            if not math.isclose(math.fsum(series), amounts[carrier], rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError(f"{carrier}: hourly values do not sum to the annual total")
            hourly[carrier] = series
        object.__setattr__(self, "hourly_by_carrier", MappingProxyType(hourly))

    @property
    def complete(self) -> bool:
        return True

    @property
    def annual(self) -> bool:
        return True

    @classmethod
    def from_hourly(cls, building, *, hourly_by_carrier: Mapping[str, Sequence[float]],
                    source: str, boundary: str = ENERGY_BOUNDARY) -> AnnualEnergy:
        """Capture a building state with 8760 delivered kWh per carrier.

        Examples
        --------
        >>> from epsm_core import Building
        >>> energy = AnnualEnergy.from_hourly(Building(), hourly_by_carrier={
        ...     'district_heating': [2.0] * 8760}, source='Teaching assumption')
        >>> energy.delivered_by_carrier['district_heating']
        17520.0
        """
        series = {k: tuple(v) for k, v in hourly_by_carrier.items()}
        return cls.for_building(building, delivered_by_carrier={
            k: math.fsum(v) for k, v in series.items()}, source=source, boundary=boundary,
            hourly_by_carrier=series)

    @classmethod
    def for_building(
        cls,
        building,
        *,
        delivered_by_carrier: Mapping[str, float],
        source: str,
        boundary: str = ENERGY_BOUNDARY,
        hourly_by_carrier: Mapping[str, Sequence[float]] | None = None,
    ) -> AnnualEnergy:
        """Capture a Core Building's current state with supplied annual kWh.

        No inputs change and no energy simulation or file access occurs.
        See the class example for the supplied energy fields.

        Parameters
        ----------
        building : epsm_core.Building
            The physical state described by these annual values.
        delivered_by_carrier : mapping
            Annual delivered kWh for each carrier, including known zeros.
        source : str
            Measurement, simulation output or an explicit assumption.
        boundary : str, optional
            Covered uses; defaults to space heating and ventilation fans.

        Returns
        -------
        AnnualEnergy
            Fixed supplied values, tied to this building state.

        Examples
        --------
        >>> from epsm_core import Building
        >>> building = Building()
        >>> energy = AnnualEnergy.for_building(building, delivered_by_carrier={'electricity': 1000}, source='Teaching assumption')
        >>> energy.state_id == building.snapshot().sha256
        True
        """
        from epsm_core import Building

        if not isinstance(building, Building):
            raise ValueError("building must be an epsm_core Building")
        return cls(building.snapshot().sha256, delivered_by_carrier, source, boundary,
                   hourly_by_carrier)

    def summary(self) -> dict:
        """Inspect source, covered uses, state and annual kWh without I/O."""
        return self.to_dict()

    def to_dict(self) -> dict:
        """Return independent supplied energy values in the versioned format."""
        result = {
            "format": "epsm-lca-energy/1",
            "state_id": self.state_id,
            "delivered_by_carrier": dict(self.delivered_by_carrier),
            "source": self.source,
            "boundary": self.boundary,
        }
        if self.hourly_by_carrier:
            result["format"] = "epsm-lca-energy/2"
            result["hourly_by_carrier"] = {k: list(v) for k, v in self.hourly_by_carrier.items()}
        return result

    @classmethod
    def from_dict(cls, value: Mapping) -> AnnualEnergy:
        """Load and validate supplied annual energy from the supported format."""
        data = dict(value)
        if data.pop("format", None) not in {"epsm-lca-energy/1", "epsm-lca-energy/2"}:
            raise ValueError("Unsupported annual energy format")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"Invalid annual energy: {error}") from error

    def __repr__(self) -> str:
        return (f"AnnualEnergy(annual_kwh={sum(self.delivered_by_carrier.values()):g}, "
                f"carriers={len(self.delivered_by_carrier)}, hourly={len(self.hourly_by_carrier)})")

    __str__ = __repr__

    def __deepcopy__(self, memo):
        return self
