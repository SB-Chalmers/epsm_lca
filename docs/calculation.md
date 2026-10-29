# How the calculation works

A renovation step is one `building.renovate(...)` call. Multiple measures in that
call form one step. Successive calls produce successive steps. Core applies the
physical changes and records what was added, removed and retained; LCA uses those
records and does not create another physical building model.

For each added occurrence, multiply the selected known quantity by each selected
installation factor. For each removed occurrence, do the same for each selected
removal factor. Factors may use mass, area, volume or count; the required basis
must actually be known. Retained occurrences are not purchased again.

Material impact this step is the sum of those contributions. Material impact so
far is the baseline contribution, if explicitly included, plus all material
steps through the current row. An unresolved earlier material total keeps later
cumulative totals unknown, while each later step's known quantities remain useful.

Operational impact uses only the reached state's annual delivered energy:
annual kWh per carrier × common period in years × sourced kg CO₂e/kWh factor.
With a yearly factor trajectory it is the sum over the period's years of annual
kWh × that year's factor, with a partial last year counted for its share.
The package does not infer which energy uses were omitted or convert thermal
demand into purchased energy. A source can be a measurement, a simulation or an
explicit assumption; storing it does not verify its accuracy.

Each row compares an entire state over the same chosen period. No operating years
are assigned to ancestors. Thus one row's total is cumulative materials plus
that row's energy. Subtracting it from the baseline total gives climate savings.
The report intentionally has no sum of all row totals: such a sum would count
several alternative operating periods together.

Boverket factors already attached to Data materials can be selected with
`AssessmentSettings.from_building`. Pass an explicitly loaded catalogue for
whole-window resources and full source versions. The helper selects conservative
production by default, or typical when requested. It never multiplies the
conservative column by the conservative multiplier again. Window factors per
kg use an explicit source conversion in kg/m² to assess known window area;
unknown physical window mass stays unknown.

The bundled source provides GWP-GHG AR4 and A5.1 installation-waste data. A5.1 is
kept separate from complete A5; selecting both is rejected to avoid overlapping
coverage. Biogenic timing, automatic future replacement, final demolition and
other environmental measures need separate future methods. Missing removal or
energy factors are not invented.

An edit that changes material identities or quantities outside a recorded
renovation leaves the affected history incomplete. Nonmaterial authoring changes
use the recorded reached state. Annual energy must match that state's identity.
The report preserves those authoring links, rather than inferring physical work.

Payback and per-area values are derived from the saved rows and are not stored
separately. Renovation carbon is material impact so far minus the baseline's.
Carbon payback divides it by the constant annual energy saving against the
baseline; a row without a positive saving has no payback. Per-area totals divide
by the single declared reference area.

All known contributions must be finite. Overflows make the appropriate totals
incomplete while preserving finite contributions. Saved-result checks allow only
floating-point rounding (relative tolerance 1e-12, absolute 1e-9 kg CO₂e), not
scientific uncertainty. Negative sourced factors are permitted.
