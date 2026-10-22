# EPSM LCA

<!-- EPSM introduction: Pocket CAD -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/welcome/epsm_lca-dark.png">
  <img src="docs/assets/welcome/epsm_lca.png" width="160" height="160" alt="EPSM LCA — One assessed material block inside a lifecycle loop; the active face identifies the assessed element.">
</picture>

Follow the climate impact of a building and its renovation steps. EPSM LCA
combines material quantities, supplied annual energy and sourced climate factors
to report impacts in kg CO₂e. Inspect each contribution, compare alternatives
and see where information is still missing.

**[Explore the EPSM platform →](https://github.com/SB-Chalmers/epsm/blob/main/docs/platform.md)**
<!-- /EPSM introduction -->

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/actions/workflows/ci.yml) [![Releases](https://img.shields.io/badge/releases-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/releases) [![Issues](https://img.shields.io/badge/issues-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/issues)

## Getting started

Requires Python 3.11+ and Git. Access to the EPSM dependency repositories is
required for the source installation below.

```sh
git clone https://github.com/SB-Chalmers/epsm_lca.git
cd epsm_lca
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "epsm_data @ git+https://github.com/SB-Chalmers/epsm_data.git@main"
python -m pip install "epsm_core @ git+https://github.com/SB-Chalmers/epsm_core.git@main"
python -m pip install -e .
```

```python
from epsm_core import Building
from epsm_lca import AssessmentSettings, assess_renovation

building = Building(preset="illustrative-reference")
report = assess_renovation(building, AssessmentSettings(30, include_energy=False))
print(report.table())
```

This example assesses materials without running an energy model. For a renovation
study, supply recorded interventions, climate factors and matching annual energy;
the [worked examples](examples/README.md) show the complete inputs.

## Documentation

- [Detailed guide](docs/guide.md)
- [Worked examples](examples/README.md)
- [Calculation rules](docs/calculation.md)
- [Migration notes](docs/migration.md)
- [Verification record](docs/verification.md)

## License

[MIT](LICENSE). Boverket and other source-data terms remain attached to their records;
the software license does not replace them.

## People and support

Developed at Chalmers University of Technology as part of the EPSM research platform.

**Funding**: Swedish Energy Agency (Project ID: P2024-04053)

**Partners**:

- Lindholmen Science Park AB
- Sinom AB
- Stiftelsen Chalmers Industriteknik

**Team**:

- **Lead Developer**: Sanjay Somanath
- **Principal Investigator**: Alexander Hollberg
- **Contributors**: Yinan Yu, Dag Wästberg

<p align="center">
  <img src="docs/assets/welcome/logos.png" width="100%" alt="Chalmers University of Technology, Chalmers Industriteknik, Sinom, Lindholmen Science Park and Swedish Energy Agency logos">
</p>
