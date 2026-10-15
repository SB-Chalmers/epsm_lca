# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Assessment choices and sourced factors; no implicit factor lookup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from epsm_core import Building
from epsm_data import Catalogue, EnvironmentalFactor

from ._validation import number, text

MATERIAL_MODULES = ("A1A3", "A4", "A5", "C1", "C2", "C3", "C4")
SUPPORTED_MODULES = (*MATERIAL_MODULES, "A5.1")
ENERGY_BOUNDARY = "space_heating_and_fans"


@dataclass(frozen=True)
class AssessmentSettings:
    """Explicit boundary, period and sourced factors; no implicit factor lookup.

    ``baseline='retained'`` assesses interventions only; ``include`` also counts
    the original inventory. Material factor keys are material IDs then modules.
    Carrier factors are in kgCO2e/kWh for B6. Sources remain in saved settings.

    Parameters
    ----------
    period_years : float
        Positive years, identical for each compared building state.
    energy_boundary : str, optional
        Covered uses; space heating and ventilation fans by default.
    baseline : {'retained', 'include'}, optional
        Retain existing materials or also count original construction once.
    material_modules : tuple of str, optional
        A1A3 production, A4 transport, A5 installation and C1--C4 removal,
        transport, treatment and disposal. All seven by default.
    material_factors, carrier_factors : mapping, optional
        Sourced Data factors by material/module or energy carrier.
    include_energy : bool, optional
        False counts materials only. Excluded energy remains None.

    Notes
    -----
    Mappings are copied and made read-only; no I/O is performed.

    Examples
    --------
    >>> settings = AssessmentSettings(30, include_energy=False)
    >>> settings.baseline
    'retained'
    >>> AssessmentSettings.from_dict(settings.to_dict()) == settings
    True
    """

    period_years: float
    energy_boundary: str = ENERGY_BOUNDARY
    baseline: str = "retained"
    material_modules: tuple[str, ...] = MATERIAL_MODULES
    material_factors: Mapping[str, Mapping[str, EnvironmentalFactor]] = field(
        default_factory=dict
    )
    carrier_factors: Mapping[str, EnvironmentalFactor] = field(default_factory=dict)
    include_energy: bool = True

    def __post_init__(self) -> None:
        period = number(self.period_years, "period_years")
        if period <= 0:
            raise ValueError("period_years must be finite and positive")
        text(self.energy_boundary, "energy_boundary")
        if not isinstance(self.baseline, str) or self.baseline not in {
            "retained",
            "include",
        }:
            raise ValueError(
                "Supply an energy boundary and baseline='retained' or 'include'"
            )
        if not isinstance(self.include_energy, bool):
            raise ValueError("include_energy must be True or False")
        if not isinstance(self.material_modules, (tuple, list)):
            raise ValueError("material_modules must be a sequence of module names")
        modules = tuple(self.material_modules)
        if not modules or any(m not in SUPPORTED_MODULES for m in modules):
            raise ValueError(
                "Select material modules from A1A3, A4, A5, A5.1, C1, C2, C3, C4"
            )
        if len(set(modules)) != len(modules):
            raise ValueError("Material modules must be unique")
        if "A5" in modules and "A5.1" in modules:
            raise ValueError("Select A5 or its waste-only part A5.1, not both")
        if not isinstance(self.material_factors, Mapping) or not isinstance(
            self.carrier_factors, Mapping
        ):
            raise ValueError("Factor collections must be mappings")
        materials = {}
        for identity, factors in self.material_factors.items():
            text(identity, "material identity")
            if not isinstance(factors, Mapping):
                raise ValueError(
                    f"{identity}: factors must map module names to factors"
                )
            for module, factor in factors.items():
                if (
                    not isinstance(factor, EnvironmentalFactor)
                    or module not in SUPPORTED_MODULES
                    or module != factor.module
                    or factor.unit == "kWh"
                ):
                    raise ValueError(
                        "Material factor module/basis does not match its mapping"
                    )
            materials[identity] = MappingProxyType(dict(factors))
        carriers = dict(self.carrier_factors)
        for carrier, factor in carriers.items():
            text(carrier, "energy carrier")
            if (
                not isinstance(factor, EnvironmentalFactor)
                or factor.module != "B6"
                or factor.unit != "kWh"
            ):
                raise ValueError("Operational factors require module B6 and unit kWh")
        object.__setattr__(self, "period_years", period)
        object.__setattr__(self, "material_modules", modules)
        object.__setattr__(self, "material_factors", MappingProxyType(materials))
        object.__setattr__(self, "carrier_factors", MappingProxyType(carriers))

    def __deepcopy__(self, memo):
        return self  # Nested mappings and Data factors are immutable.

    @classmethod
    def from_building(
        cls,
        building: Building,
        *,
        period_years: float,
        catalogue: Catalogue | None = None,
        production: str = "conservative",
        **choices,
    ) -> AssessmentSettings:
        """Use Boverket factors already supplied by Data for this renovation path.

        Parameters
        ----------
        building : epsm_core.Building
            Current building with its recorded renovation steps.
        period_years : float
            Common assessment period.
        catalogue : epsm_data.Catalogue, optional
            An explicitly loaded catalogue, needed for whole-window resources
            and their area conversion. Nothing is loaded automatically.
        production : {'conservative', 'typical'}, optional
            Which Boverket production column to select; conservative by default.
        **choices
            Other settings, including explicit material-factor overrides.

        Returns
        -------
        AssessmentSettings
            Known factors with sources; absent removal/energy factors stay absent.

        Notes
        -----
        Boverket's A5.1 is installation waste, not the whole A5 stage. It is
        retained as A5.1 evidence and is not silently used as complete A5.

        Examples
        --------
        Use the explicitly loaded catalogue's existing climate records.

        >>> from epsm_data import Catalogue
        >>> from epsm_core import Building
        >>> catalogue = Catalogue.load()
        >>> constructions = catalogue.for_year('multi_family', 1960, state='existing').construction_set
        >>> building = Building(construction_set=constructions)
        >>> settings = AssessmentSettings.from_building(building, period_years=30, catalogue=catalogue)
        >>> len(settings.material_factors) > 0
        True
        """
        from .boverket import building_factors

        factors = building_factors(building, catalogue=catalogue, production=production)
        choices.setdefault(
            "material_modules", ("A1A3", "A4", "A5.1", "C1", "C2", "C3", "C4")
        )
        for identity, overrides in choices.pop("material_factors", {}).items():
            factors.setdefault(identity, {}).update(overrides)
        return cls(period_years=period_years, material_factors=factors, **choices)

    def summary(self) -> dict:
        """Return bounded assessment choices and factor counts without I/O."""
        return {
            "period_years": self.period_years,
            "energy_boundary": self.energy_boundary,
            "baseline": self.baseline,
            "material_modules": self.material_modules,
            "include_energy": self.include_energy,
            "material_factor_count": sum(
                len(factors) for factors in self.material_factors.values()
            ),
            "carrier_factor_count": len(self.carrier_factors),
        }

    def __repr__(self) -> str:
        summary = self.summary()
        return (
            f"AssessmentSettings(years={self.period_years:g}, baseline={self.baseline!r}, "
            f"energy={self.include_energy}, "
            f"material_factors={summary['material_factor_count']}, "
            f"carrier_factors={summary['carrier_factor_count']})"
        )

    def to_dict(self) -> dict:
        return {
            "format": "epsm-lca-settings/1",
            "period_years": self.period_years,
            "energy_boundary": self.energy_boundary,
            "baseline": self.baseline,
            "material_modules": self.material_modules,
            "include_energy": self.include_energy,
            "material_factors": {
                key: {module: factor.to_dict() for module, factor in factors.items()}
                for key, factors in self.material_factors.items()
            },
            "carrier_factors": {
                key: factor.to_dict() for key, factor in self.carrier_factors.items()
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping) -> AssessmentSettings:
        """Load current or unversioned settings and validate their factor records."""
        if not isinstance(value, Mapping):
            raise ValueError("Assessment settings must be a mapping")
        data = dict(value)
        if "format" not in data and any(
            name not in data
            for name in (
                "period_years",
                "energy_boundary",
                "baseline",
                "material_modules",
            )
        ):
            raise ValueError(
                "Old settings lack recorded assessment choices; supply them explicitly"
            )
        if data.pop("format", "epsm-lca-settings/1") != "epsm-lca-settings/1":
            raise ValueError("Unsupported assessment settings format")
        if not isinstance(data.get("material_factors", {}), Mapping) or not isinstance(
            data.get("carrier_factors", {}), Mapping
        ):
            raise ValueError("Saved factor collections must be mappings")
        if any(
            not isinstance(factors, Mapping)
            for factors in data.get("material_factors", {}).values()
        ):
            raise ValueError("Saved material factors must map modules to factors")
        try:
            data["material_factors"] = {
                key: {
                    module: EnvironmentalFactor(**factor)
                    for module, factor in factors.items()
                }
                for key, factors in data.get("material_factors", {}).items()
            }
            data["carrier_factors"] = {
                key: EnvironmentalFactor(**factor)
                for key, factor in data.get("carrier_factors", {}).items()
            }
            return cls(**data)
        except (TypeError, AttributeError) as error:
            raise ValueError(f"Invalid assessment settings: {error}") from error
