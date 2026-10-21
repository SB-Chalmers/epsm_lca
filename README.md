# epsm_lca

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/actions/workflows/ci.yml) [![Releases](https://img.shields.io/badge/releases-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/releases) [![Issues](https://img.shields.io/badge/issues-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm_lca/issues)

Calculate the climate impact of building materials, annual delivered energy and
renovation steps. LCA uses explicit quantities and sourced climate factors, and
reports missing inputs alongside results in kg CO₂e.

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
