# Methodology

This document explains exactly what the biological-age number on your dashboard means,
where every constant in the calculation comes from, and where the calculation is weak.
It is written for a skeptical reader who wants to decide whether to trust the numbers,
not to sell them.

Every equation and constant below is transcribed from the code that ships in this
repository — `backend/src/bioage/estimators/*.py` and `backend/src/bioage/reference/*.yaml`
— not from the design plan that preceded implementation. Where the plan and the shipped
code disagree, the code wins, and the disagreement is called out explicitly (see
"Correction to the source research" and the per-estimator notes below).

## 1. What this is and is not

**This is a fitness and autonomic-nervous-system proxy, built entirely from consumer
wrist-wearable data.** It combines four independent estimators — a non-exercise fitness
age, an HRV-based age, a step-count mortality-equivalent age, and a Klemera–Doubal-style
composite biomarker age — into a single inverse-variance-weighted number with a
confidence interval.

**This is not a validated biological aging clock.** The gold-standard clocks in the
literature (Horvath, GrimAge, DunedinPACE from DNA methylation; Levine PhenoAge and the
original Klemera–Doubal method from blood chemistry) are trained and validated against
mortality and morbidity outcomes in large cohorts, using inputs a wrist wearable cannot
produce. Nothing in this project has been validated against a mortality outcome. What
this project reuses from that literature is the *math* — KDM's algebra, a published
non-exercise VO2max equation, a published step-count/mortality dose-response curve — not
the underlying validated biomarker panels.

**The error bars are wide — several years, typically ±7 to ±13 years at the 95% level —
and they should be taken seriously.** A single week's estimate can move for reasons that
have nothing to do with aging: a bad flu, a stressful travel week, a broken sleep
schedule, or simply a thin data window. **The trend across many weeks is far more
informative than any single value.** Treat this as you would a bathroom scale that also
happens to estimate your cardiovascular fitness: useful for noticing a slow drift over
months, not for diagnosing a Tuesday.

## 2. Inputs

### Primary biomarkers (drive the age estimators directly)

| Biomarker | Source | Used by |
|---|---|---|
| Resting heart rate (RHR) | `daily-resting-heart-rate` | NTNU fitness age, KDM |
| HRV RMSSD (nightly, deep-sleep preferred) | `daily-heart-rate-variability` | HRV-norm age, KDM |
| Steps (daily count) | `steps` | NTNU physical-activity index, step-count mortality age, KDM |
| Sleep efficiency, derived (see §6.5) | `sleep` | KDM |

Respiratory rate (`daily-respiratory-rate`) and Active Zone Minutes
(`active-zone-minutes`) are also ingested. Respiratory rate is carried in the feature
vector but not consumed by any estimator today. Active Zone Minutes feeds only the NTNU
physical-activity index as an intensity bonus (§6.1).

### Computed but not yet consumed

Ingested and parsed into `daily_metrics`, but not fed into any age estimator, and not
currently surfaced anywhere in the frontend either — dormant, not "trend-only display"
signals, despite each having a good reason (noted below) *why* an estimator doesn't use
it directly.

| Signal | Source | Status |
|---|---|---|
| SpO₂ (average daily) | `daily-oxygen-saturation` | Deliberately excluded as an age component — too dependent on altitude, device fit, and short-term illness to anchor an age estimate. Not surfaced in the UI: `DailyMetricOut` (`backend/src/bioage/api/schemas.py`) does not expose it, and no frontend page calls `GET /api/daily-metrics`. |
| Skin temperature delta | `daily-sleep-temperature-derivations` | Meaningful only as a multi-week deviation from personal baseline, not as an absolute value with an age relationship. Same gap as SpO₂: not in `DailyMetricOut`, not called from the frontend. |
| Sleep regularity (circular SD of sleep midpoints, minutes) | derived from `sleep` (§6.5) | Computed by `regularity.py` and stored on every `BiomarkerVector`, but no estimator reads it and it is not surfaced in the frontend today. |

### Query-range cap

Every data type this project reads — `daily-resting-heart-rate`,
`daily-heart-rate-variability`, `daily-respiratory-rate`, `daily-oxygen-saturation`,
`daily-sleep-temperature-derivations`, `steps`, `active-zone-minutes`, `sleep`, `weight`,
`height`, and `daily-vo2-max` — is queried under Google's **90-day** maximum query
range. Google's data-types documentation
(https://developers.google.com/health/data-types, verified 2026-08-02) states that only
four data types are capped at 14 days instead: `calories-in-heart-rate-zone`,
`heart-rate`, `active-minutes`, and `total-calories`. None of those four are registered
by this project (`backend/src/bioage/ingest/registry.py`), so no data type this project
reads is subject to the 14-day cap — including `steps`, which an earlier version of this
project wrongly capped at 14 days (§8.3).

### User-supplied profile fields

Sex, birthdate, height, weight, and waist circumference are entered by the user, not
read from the wearable. Height and weight combine into BMI for KDM. Waist circumference
and sex are required by the NTNU fitness-age equation; sex is also required by the
HRV-norm equation, which is sex-stratified. Chronological age is derived from birthdate
as of the date a given week is scored, not as of "today" — this matters for scoring
historical weeks correctly.

The Fitbit Air does not produce VO2max (Google Health derives that field only from
GPS-tracked runs, which the Air does not do), so it is polled and expected to come back
empty; no estimator here depends on it.

## 3. Feature window

Every estimate is built from a **30-day trailing window** (`WINDOW_DAYS = 30` in
`backend/src/bioage/biomarkers/features.py`), aggregated with **medians, not means**. A
median is robust to the kind of single-night outlier a wearable produces constantly — a
watch worn loosely for one night, a red-eye flight, a night the device simply failed to
sync — without needing to hand-write outlier detection. A mean would let one bad night
drag a 30-day estimate around; a median mostly ignores it.

Two independent coverage gates apply:

- **Window-level gate.** A window needs at least `MIN_WINDOW_DAYS = 14` days of *any*
  data before it produces a vector at all. Below that, `build_vector` returns `None` and
  the week is not scored.
- **Low-confidence gate.** A window with fewer than `LOW_CONFIDENCE_DAYS = 21` days of
  data still produces an estimate, but is flagged `is_low_confidence = True`, which
  widens the composite's confidence interval by 1.6× (§5).
- **Per-biomarker minimums.** Each biomarker additionally needs its own minimum number
  of populated days within the window before its median is computed at all; below the
  minimum it contributes `None` rather than a median built from too few nights:
  - `MIN_RHR_DAYS = 10`
  - `MIN_HRV_DAYS = 10`
  - `MIN_STEPS_DAYS = 14`
  - `MIN_SLEEP_DAYS = 10`

  Active Zone Minutes and respiratory rate use a minimum of 1 day (any single reading is
  used), since they are not treated as core biomarkers.

A biomarker below its minimum simply drops out of that week's `BiomarkerVector`; each
estimator (§4) declares its own required subset and returns `None` for a week where it
cannot run, rather than substituting a default.

## 4. Each estimator

Every estimator is a pure function of a `BiomarkerVector` returning an `EstimatorResult`
(component name, age in years, sigma in years, and the inputs used) or `None` when its
required inputs are missing. An age is never reported without an accompanying sigma: the
composite (§5) weights every component by its inverse variance, so a component with no
uncertainty estimate cannot be combined honestly.

All estimators clamp their output to `[AGE_FLOOR, AGE_CEILING] = [18, 100]` years
(`backend/src/bioage/estimators/models.py::clamp_age`), because extrapolating a linear
or log-linear equation far outside the age range it was fit on produces numbers that are
arithmetically valid and biologically meaningless.

### 4.1 NTNU non-exercise fitness age

**Source:** Nes BM, Janszky I, Wisløff U, Støylen A, Karlsen T. "Age-predicted maximal
heart rate in healthy subjects: The HUNT Fitness Study." *Scand J Med Sci Sports*
2013;23:697-704. Non-exercise VO2max coefficients from the HUNT Fitness Study
(n=3,320), standard error of the estimate (SEE) 3.5 mL/kg/min. `derived: false` in
`ntnu.yaml` — these coefficients are copied verbatim from the published equation, not
refit.

**Equation.** VO2max is estimated from age, sex, a physical-activity index, waist
circumference, and resting heart rate:

```
VO2max = intercept + age·age_coef + physical_activity·pa_coef
       + waist_cm·waist_coef + resting_hr_bpm·rhr_coef
```

with sex-specific coefficients (`backend/src/bioage/reference/ntnu.yaml`):

| Coefficient | Male | Female |
|---|---|---|
| intercept | 100.27 | 74.74 |
| age | −0.296 | −0.247 |
| physical_activity | 0.226 | 0.198 |
| waist | −0.369 | −0.259 |
| resting_hr | −0.155 | −0.114 |

**Fitness age** is *not* age itself — it is defined by inverting the same equation at
population-typical (reference) inputs and solving for the age at which a *typical*
person would have the subject's estimated VO2max:

```
baseline = intercept + pa_coef·PA_ref + waist_coef·WC_ref + rhr_coef·RHR_ref
fitness_age = (VO2max − baseline) / age_coef
```

Reference-population values (`ntnu.yaml`, HUNT-cohort midpoints):

| | Male | Female |
|---|---|---|
| physical_activity | 5.0 | 5.0 |
| waist_cm | 94.0 | 84.0 |
| resting_hr_bpm | 66.0 | 70.0 |

Using the *same* equation in both directions guarantees the round-trip identity
`fitness_age(vo2max(age, reference inputs)) == age` — a subject with exactly
population-typical activity, waist, and RHR at age A gets fitness age A back, regardless
of the coefficients' exact values.

**σ = 5.9 years** (`pa_index.yaml: fitness_age_sigma_years`). Derivation: the published
VO2max equation has SEE 3.5 mL/kg/min; dividing by the male age coefficient's magnitude
(0.296 mL/kg/min per year) converts that into an age-equivalent spread of
3.5 / 0.296 ≈ 11.8 years, which is then treated as a 2σ spread, giving σ ≈ 5.9 years.

**Failure modes.** Requires `waist_cm` and `resting_hr_bpm`; returns `None` without them.
The physical-activity index is itself an approximation (§6.1) — this is the single
weakest input to this estimator. Waist circumference is self-reported and never
re-measured automatically, so a stale value silently biases every subsequent week.

### 4.2 HRV-norm age

**Source:** log-linear fit of nightly RMSSD against age, `derived: true` in
`hrv_norms.yaml`. See §8.2 for why these coefficients differ from the plan's original
proposal.

**Equation.** RMSSD is modeled as declining log-linearly with age:

```
ln(RMSSD) = ln_intercept + ln_slope · age
```

inverted in closed form:

```
age = (ln(RMSSD) − ln_intercept) / ln_slope
```

Sex-stratified coefficients (`backend/src/bioage/reference/hrv_norms.yaml`):

| | ln_intercept | ln_slope |
|---|---|---|
| Male | 4.517350774886466 | −0.017123740486994162 |
| Female | 4.547350774886466 | −0.017123740486994162 |

The female coefficients use the same slope with +0.03 added to the log-intercept — a
multiplicative offset on the fitted curve reflecting the small sex difference reported
in RMSSD normative studies.

RMSSD is clamped to `[min_rmssd_ms, max_rmssd_ms] = [5.0, 250.0]` before inversion, to
keep implausible sensor readings from producing an implausible age.

**σ = 7.0 years** (`hrv_norms.yaml: sigma_years`). Derivation, from the file's own
comment: nightly wrist-PPG RMSSD carries MAPE frequently above 10% against an ECG
reference (Dial et al. 2025); propagating a 12% measurement error through the fitted
slope (≈0.0171 per year in log space) gives roughly 7 years of age-equivalent
uncertainty.

**Failure modes.** Returns `None` if RMSSD is missing or non-positive. Wrist PPG HRV is
materially noisier than a chest strap or ECG (§6.4), which is why this component also
carries the largest `sigma_multiplier` in the composite (§5).

### 4.3 Step-count mortality-equivalent age

**Source:** Paluch AE, Bajpai S, Bassett DR, et al. "Daily steps and all-cause
mortality: a meta-analysis of 15 international cohorts." *Lancet Public Health*
2022;7(3):e219-e228 (47,471 adults, 3,013 deaths). `derived: true` in
`steps_mortality.yaml` — the hazard-ratio knots are digitised from the paper's reported
dose-response curve and rescaled so `reference_steps` has hazard ratio 1.0.

**Equation.** A piecewise-linear lookup converts mean daily steps to an all-cause
mortality hazard ratio relative to 7,500 steps/day (`reference_steps`):

| Mean daily steps | Hazard ratio |
|---|---|
| 0 | 1.70 |
| 2,000 | 1.52 |
| 4,000 | 1.26 |
| 6,000 | 1.09 |
| 7,500 | 1.00 |
| 9,000 | 0.94 |
| 10,000 | 0.90 |
| 12,000 | 0.86 |
| 14,000 | 0.84 |

A single plateau at 14,000 steps is used as a conservative simplification; the source
paper's benefit plateau is reported as roughly 6,000-10,000 steps/day in older adults and
8,000-10,000 in younger adults.

The hazard ratio is converted to an age offset using the Gompertz law — adult mortality
hazard roughly doubles every `mrdt_years = 8.0` years:

```
age_offset = ln(hazard_ratio) / ln(2) · mrdt_years
age = chronological_age + age_offset
```

A subject walking exactly the reference step count (7,500/day) has hazard ratio 1.0,
`ln(1.0) = 0`, and so this estimator returns their chronological age unchanged.

**σ = 8.0 years** (`steps_mortality.yaml: sigma_years`).

**Failure modes.** Returns `None` if steps are missing. The mapping from a
population-level hazard ratio to an individual age offset via Gompertz doubling time is
itself an approximation — a hazard ratio describes a cohort's risk distribution, not a
guaranteed individual effect.

### 4.4 Klemera–Doubal (KDM-style) biomarker age

**Source:** Klemera P, Doubal S. "A new approach to the concept and computation of
biological age." *Mech Ageing Dev* 2006;127(3):240-8. **Constants are derived, not
primary** — see §6.2 and §7 for how, and §8.1 for a correction to the formula as printed
in this project's own source-research document.

**Equation.** For each biomarker *j*, the reference population is assumed to satisfy a
linear regression on chronological age, `x_j = q_j + k_j·age`, with residual standard
deviation `s_j`. The uncorrected Klemera–Doubal estimator inverts that system:

```
BA_E = Σ_j[(x_j − q_j)·k_j / s_j²] / Σ_j[k_j² / s_j²]
```

and the age-corrected form (`BA_EC`) pulls the estimate toward chronological age `CA`
using a characteristic variance `s_BA²`:

```
BA_EC = [Σ_j((x_j − q_j)·k_j / s_j²) + CA / s_BA²]
      / [Σ_j(k_j² / s_j²)            + 1  / s_BA²]
```

This project always applies the correction (`s_ba = 11.0` is set in `kdm_biomarkers.yaml`
and passed to every call), so the estimator in production always computes `BA_EC`, never
the bare `BA_E`.

**The denominator squares `k_j`, not `k_j/s_j²`.** This is the exact point on which the
plan's source-research document is wrong; see §8.1 for the full correction and the guard
test that pins it down.

Reference regression constants (`backend/src/bioage/reference/kdm_biomarkers.yaml`,
`derived: true`, `min_biomarkers: 3`, `s_ba: 11.0`):

| Biomarker | q | k | s |
|---|---|---|---|
| resting_hr_bpm | 63.261905 | 0.111429 | 9.924169 |
| hrv_rmssd_ms | 73.285714 | −0.645714 | 16.172728 |
| mean_daily_steps | 12138.095238 | −91.428571 | 3366.619519 |
| sleep_efficiency_pct | 97.452381 | −0.205714 | 6.120678 |
| bmi | 26.621429 | 0.038571 | 6.160241 |

At least `min_biomarkers = 3` of these five must be present in a given week's
`BiomarkerVector` or the estimator returns `None`.

**σ is derived per call, not a fixed constant — this is one of the most important
honesty points in this document.** The denominator above is exactly the Fisher
information about age carried by the inputs, so KDM's own uncertainty falls out of the
same quantity:

```
sigma = sqrt( 1 / ( Σ_j(k_j²/s_j²) + 1/s_BA² ) )
```

With all five biomarkers present, `Σ_j k_j²/s_j² = 3.6265 × 10⁻³` (computed directly
from the table above) against `1/s_BA² = 1/11² = 8.2645 × 10⁻³`, giving
**σ ≈ 9.17 years**. With only three biomarkers (say resting HR, HRV, and steps),
`Σ_j k_j²/s_j² = 2.4577 × 10⁻³`, giving **σ ≈ 9.66 years** — noticeably wider, because
fewer inputs carry less information about age.

**Why this matters:** with all five biomarkers, the chronological-age anchor term
(`1/s_BA²`) carries `8.2645 / (3.6265 + 8.2645) ≈ 69.5%` of the total weight in both the
numerator and the σ calculation, and the five biomarkers together carry only the
remaining `≈30.5%`. **KDM is therefore substantially a restatement of chronological age,
lightly nudged by the biomarkers** — not an independent biomarker-only clock. This is a
direct, load-bearing consequence of `s_ba = 11.0` being wide relative to the
biomarker-only information available from five wearable-derived signals. An earlier,
narrower fixed sigma (6.5 years, from the original plan) was removed specifically
because it would have overstated KDM's independence from chronological age and let the
composite over-trust a component that is mostly agreeing with the age you already told
it.

**A domain edge worth knowing about explicitly: athletic young users saturate at the
age floor.** A fit 25-year-old fixture (RHR 52 bpm, RMSSD 65 ms, 13,000 steps/day, sleep
efficiency 94%, BMI 22) produces `BA_EC ≈ 18.64` years — only 0.64 years above the
`AGE_FLOOR` of 18. This is not a bug; it is what the linear extrapolation produces at the
edge of the fitted range, clamped to stay biologically plausible. Realistic mid-life
profiles do not clamp — the floor only bites for genuinely exceptional young, fit users.
If you are at that end of the range, treat the estimate as "the floor of what this model
can express," not as a precise number.

**Failure modes.** Requires at least 3 of the 5 biomarkers. Because the KDM reference
constants are themselves derived (not primary NHANES parameters — §6.2), this component
is better described as "KDM-style" than as a validated Klemera–Doubal implementation.

## 5. The composite

**Source:** `backend/src/bioage/estimators/composite.py`, constants in
`backend/src/bioage/reference/composite.yaml`.

The four component estimates are combined by **inverse-variance weighting**, the
maximum-likelihood combination of independent estimates of the same underlying quantity:

```
age   = Σ_i(age_i / sigma_i²) / Σ_i(1 / sigma_i²)
sigma = sqrt(1 / Σ_i(1 / sigma_i²))
```

Before combination, each component's own sigma is multiplied by a fixed per-component
multiplier (`sigma_multipliers` in `composite.yaml`), which downweights components whose
uncertainty is understated relative to the others or whose input signal is known to be
noisier:

| Component | Multiplier |
|---|---|
| ntnu_fitness | 1.0 |
| kdm | 1.0 |
| steps_mortality | 1.1 |
| hrv_norm | 1.3 |

**HRV is downweighted the most (1.3×)** because wrist-PPG HRV is materially noisier than
an ECG reference (§4.2, §6.4); its already-wide σ = 7.0 years is inflated further before
it competes for weight against the other components.

The 95% confidence interval uses **z = 1.96** (`composite.yaml: z_score`):

```
half_width = z_score · sigma
ci_low  = age − half_width
ci_high = age + half_width
```

**Low-confidence inflation.** When a week's data coverage is thin
(`total_days < LOW_CONFIDENCE_DAYS = 21`, §3), the combined sigma is inflated by
`low_confidence_sigma_multiplier = 1.6` *after* the inverse-variance combination, before
the confidence interval is computed. This widens the reported band rather than silently
producing a falsely-precise number from a thin window.

**A composite is refused below `min_components = 2`.** If fewer than two component
estimators produced a result for a given week (e.g., missing waist circumference and too
few HRV nights), `combine()` returns `None` and no composite is scored for that week —
because a single estimator dressed up as a multi-method consensus would misrepresent its
own uncertainty.

### 5.1 The composite's chronological-age sensitivity

**This is the single most important number for a skeptical reader interpreting the
chart's slope, and it was recomputed directly from the shipped constants for this
document rather than trusted from an earlier draft.**

Two of the four component estimators are literally `chronological_age + offset`:

- **NTNU fitness age** (§4.1): `fitness_age = (VO2max(CA, other inputs) − baseline) /
  age_coef`, and `VO2max` is linear in `CA` with coefficient `age_coef` — so
  `d(fitness_age)/d(CA) = age_coef / age_coef = 1` exactly, holding every other input
  (waist, resting HR, physical activity) fixed.
- **Step-count mortality age** (§4.3): `age = CA + ln(hazard_ratio)/ln(2) · mrdt_years`,
  and `hazard_ratio` depends only on steps, never on `CA` — so
  `d(steps_age)/d(CA) = 1` exactly.
- **HRV-norm age** (§4.2) depends only on measured RMSSD, never on `CA` —
  `d(hrv_age)/d(CA) = 0`. This is the *only* component that carries information about
  age independent of the birthdate the user typed into the Profile page.
- **KDM** (§4.4) blends a biomarker-only estimate with the chronological-age anchor
  term; `d(BA_EC)/d(CA)` is exactly the anchor's *share* of the total Fisher
  information, `(1/s_BA²) / (Σ_j k_j²/s_j² + 1/s_BA²)`. With all five biomarkers
  present this is the **≈69.5%** figure already derived in §4.4.

The composite is an inverse-variance-weighted average of these four, and the weights
(each component's own multiplier-scaled σ) do not depend on `CA` — so the composite's
own sensitivity is the same weighted average of the four components' individual
sensitivities above:

```
d(composite)/d(CA) = Σ_i[ w_i · d(age_i)/d(CA) ] / Σ_i w_i,   w_i = 1 / (σ_i · multiplier_i)²
```

Using the shipped constants (σ = 5.9, 7.0, 8.0, 9.17 years for ntnu_fitness, hrv_norm,
steps_mortality, kdm respectively — the KDM figure is its all-five-biomarker σ from
§4.4 — and the composite.yaml multipliers 1.0, 1.3, 1.1, 1.0):

| Component | σ (years) | multiplier | effective σ | weight = 1/σ_eff² | d(age)/d(CA) |
|---|---|---|---|---|---|
| ntnu_fitness | 5.9 | 1.0 | 5.9 | 0.02873 | 1.0 |
| hrv_norm | 7.0 | 1.3 | 9.1 | 0.01208 | 0.0 |
| steps_mortality | 8.0 | 1.1 | 8.8 | 0.01291 | 1.0 |
| kdm | 9.17 | 1.0 | 9.17 | 0.01189 | 0.695 |

`Σ w_i = 0.06561`; `Σ w_i · d(age_i)/d(CA) = (0.02873×1) + (0.01208×0) + (0.01291×1) +
(0.01189×0.695) = 0.04991`.

**`d(composite)/d(CA) = 0.04991 / 0.06561 ≈ 0.76`.** This was cross-checked by
numerically differentiating the actual `estimate_all()` code at a representative
profile with every biomarker present (central difference, h = 1e-4 years, all four
components running), which reproduces **0.76066** — matching the hand calculation above
to four decimal places.

**What this means:** the composite rises roughly **three-quarters of a year per
calendar year purely by construction** — not because the user's fitness or physiology is
declining, but because two of the four components are chronological age plus a bounded
offset, and the fourth (KDM) is majority-weighted toward chronological age by its own
`s_BA` anchor (§4.4, §6.2). Only HRV age (0% sensitivity) carries information genuinely
independent of the birthdate entered on the Profile page. Read the chart's *slope*
skeptically, not just its level: a line climbing at roughly 0.76 years per calendar
year — tracking the passage of time almost one-for-one — is close to what this model
produces by construction even with no real change in fitness or physiology, not evidence
of aging. A materially different slope — flatter (improvements outrunning the built-in
drift) or steeper (decline outrunning it) — is the signal actually worth attending to.

## 6. Known approximations

### 6.1 The PA index is not the HUNT questionnaire index

The HUNT non-exercise VO2max equation (§4.1) takes a physical-activity index that, in
the original HUNT study, comes from a **questionnaire** scoring the frequency, duration,
and intensity of exercise (Nes et al. 2011). **No published mapping from step counts to
that questionnaire index exists.** This project approximates it with a piecewise-linear
lookup from wearable data, and this is **the weakest input in the NTNU estimator.**

Knot table (`backend/src/bioage/reference/pa_index.yaml`):

Base index from mean daily steps:

| Steps/day | Index |
|---|---|
| 0 | 0.0 |
| 2,000 | 1.0 |
| 4,000 | 2.5 |
| 6,000 | 4.0 |
| 7,500 | 5.0 |
| 10,000 | 6.5 |
| 12,500 | 7.5 |
| 15,000 | 8.5 |
| 20,000 | 10.0 |

Intensity bonus added from mean daily Active Zone Minutes (added to the base, capped at
`index_ceiling = 15.0`):

| AZM/day | Bonus |
|---|---|
| 0 | 0.0 |
| 10 | 0.5 |
| 22 | 1.5 |
| 45 | 3.0 |
| 90 | 4.5 |

The knots were chosen so that sedentary (<4,000 steps/day) sits near the bottom of the
scale, the population-typical 7,000-8,000 steps/day lands on the reference value of 5.0
used in `ntnu.yaml`, and highly active (>15,000 steps/day) approaches the ceiling. This
is a judgment call, not a measurement — Active Zone Minutes is added as an intensity
bonus specifically because the real HUNT index weights exercise intensity, which raw
step count alone cannot express, but the resulting index is still a proxy for a
questionnaire answer, not the answer itself. If neither steps nor AZM are available for
a week, a `fallback_index = 5.0` (the reference population value) is used instead, which
means a data-sparse week silently assumes population-typical activity rather than
propagating "unknown."

### 6.2 KDM reference constants are derived, not primary

No published NHANES q/k/s parameter table exists for the specific wearable-derived
biomarkers used here (resting HR, RMSSD, mean daily steps, sleep efficiency, BMI). The
Klemera–Doubal method as published assumes access to a large reference cohort's
individual-level regression parameters for whatever biomarker panel is used; that table
does not exist for a Fitbit's biomarker set.

Instead, `backend/src/bioage/reference/regenerate_kdm.py` derives `q` (intercept), `k`
(age slope), and `s` (pooled residual SD) by ordinary least squares over age-stratified
normative summary statistics — six age-midpoint, mean, within-stratum-SD triples per
biomarker, drawn from the sources cited per-biomarker in §4.4's table (Ostchega et al.
for RHR, Althoff et al. 2017 and NHANES accelerometry summaries for steps, Ohayon et al.
2004 for sleep efficiency, NHANES anthropometry for BMI, and this project's own HRV
normative fit for RMSSD). The residual SD `s` combines both the within-stratum spread
reported in the source and the linear fit's own lack-of-fit to those stratum means
(`s = hypot(pooled_within_sd, lack_of_fit)`), so it is deliberately conservative rather
than an underestimate.

This makes the KDM component **"KDM-style,"** not a published NHANES KDM implementation:
the algebra is the real Klemera–Doubal method, but the reference population it is
computed against is a reconstruction from published summary statistics, not raw
individual-level NHANES data. See §7 for how to audit or regenerate these constants.

### 6.3 Reference-population sensitivity

The NTNU fitness-age inversion (§4.1) is defined relative to `reference_population`
values in `ntnu.yaml` (physical activity, waist circumference, resting HR, by sex).
**Changing any of these values shifts every computed fitness age by a constant offset**
— because the inversion is `(VO2max − baseline) / age_coef`, and `baseline` is linear in
the reference values. This is not a bug to be tuned away; it is inherent to defining
"fitness age" as "the age at which a population-typical person would have your VO2max."
If you change `reference_population` to reflect a different reference cohort, expect
every historical fitness-age value to shift, and treat any before/after comparison
across that change as invalid.

### 6.4 Wrist PPG HRV noise

Consumer wrist-worn photoplethysmography (PPG) HRV, including nightly RMSSD as reported
by the Fitbit Air, has a mean absolute percentage error (MAPE) **frequently above 10%**
against a chest-strap or ECG reference (Dial et al. 2025, cited in `hrv_norms.yaml`).
This is a real limitation of the sensing modality, not a defect in this project's
inversion of the RMSSD/age relationship — it is why the HRV-norm estimator carries a
wide σ = 7.0 years (§4.2) and the largest composite downweighting multiplier (1.3×, §5).

### 6.5 Sleep efficiency and WASO are derived, not reported by the API

The Google Health Sleep message does not carry sleep efficiency or wake-after-sleep-onset
(WASO) as fields. Both are computed in `backend/src/bioage/biomarkers/parsers/sleep.py`
from the raw session interval and stage timeline:

```
time_in_bed = session.endTime − session.startTime
asleep      = duration(LIGHT) + duration(DEEP) + duration(REM)
efficiency  = asleep / time_in_bed × 100
WASO        = sum of AWAKE-stage durations strictly between
              the first and last non-awake stage
```

**WASO deliberately excludes leading and trailing wakefulness.** Time spent awake before
falling asleep or after waking but before getting up is time in bed awake, not
wakefulness *after sleep onset* by definition — including it would conflate "took a
while to fall asleep" with "woke up in the middle of the night," which have different
clinical meanings. `deep_pct` and `rem_pct`, when reported, are fractions of time
*asleep* (not time in bed), consistent with how sleep-stage percentages are normally
reported.

**Sleep midpoints carry a related, separate limitation worth flagging here.** Sleep
regularity (`backend/src/bioage/biomarkers/regularity.py`) is computed as the circular
standard deviation of nightly sleep midpoints, read from each session's own timestamp
offset with **no explicit conversion to a fixed local timezone**. Circular SD is
rotation-invariant, so a *constant* UTC offset — living in one timezone the whole
window — cannot bias the regularity statistic; only a *change* in offset within a 30-day
window matters. A daylight-saving-time transition falling inside a 30-day window injects
a spurious ~60-minute shift into that window's sleep-midpoint calculation, twice a year,
for users whose Fitbit reports timestamps in a DST-observing local offset. This is a
known limitation, not a computed bug: no explicit fix is applied, and the effect is
small and self-correcting (the affected window ages out after 30 days).

## 7. Reproducing the constants

The KDM reference table (§4.4, §6.2) is not hand-edited. To regenerate
`backend/src/bioage/reference/kdm_biomarkers.yaml` from the normative tables embedded in
the regeneration script:

```bash
cd backend && uv run python -m bioage.reference.regenerate_kdm
```

To audit what went into it, read `backend/src/bioage/reference/regenerate_kdm.py`
directly: the `NORMS` dictionary at the top of the file lists, per biomarker, the exact
six `(age_midpoint, mean, within_stratum_sd)` triples and their citation, and the `fit()`
function shows the OLS regression and the `hypot(pooled_within, lack_of_fit)` residual-SD
calculation described in §6.2. Changing a triple in `NORMS` and re-running the module is
the supported way to update these constants — do not hand-edit the generated YAML.

To verify every constant currently loaded by the application against this document,
run:

```bash
cd backend && uv run python -c "
from bioage.reference.loader import get_composite, get_hrv_norms, get_kdm, get_ntnu, get_pa_index
for name, fn in [('ntnu', get_ntnu), ('pa_index', get_pa_index), ('hrv', get_hrv_norms),
                 ('kdm', get_kdm), ('composite', get_composite)]:
    c = fn()
    print(f'--- {name} (derived={c.derived}) ---')
    print(c.model_dump_json(indent=2))
"
```

Every numeric value in this document was cross-checked against this command's output
while writing it (see the task-28 report for the full dump).

## 8. Corrections to the source research and the original plan

Three places where an earlier version of this project — the source-research document or
the implementation plan that followed it — was wrong, and what the shipped code does
instead.

### 8.1 The KDM denominator

The project's own source-research document — a working note that seeded this design and is
kept outside the repository — prints the Klemera–Doubal denominator incorrectly. It states:

```
BA_E = [ Σ_j (x_j − q_j)(k_j / s_j²) ] / [ Σ_j (k_j / s_j²)² ]
```

i.e. it squares the whole term `k_j/s_j²`. **This is wrong.** The correct
Klemera–Doubal denominator squares only `k_j`, dividing by `s_j²` once:

```
BA_E = Σ_j[(x_j − q_j)·k_j / s_j²] / Σ_j[k_j² / s_j²]
```

This is what `backend/src/bioage/estimators/kdm.py` implements, and the distinction is
not cosmetic. **Only the correct denominator satisfies the defining identity of the
method:** if a subject's biomarkers lie exactly on the reference regression line for
every biomarker (`x_j = q_j + k_j·A` for all `j`), the estimator must return exactly
`A`. Using the source document's denominator on the test fixture in
`backend/tests/estimators/test_kdm.py` (three biomarkers with `k = 0.30, -0.20, 0.10`
and `s = 6.0, 4.0, 2.0`) and evaluating at ages 25, 40, 55, and 70 produces results of
roughly 220, 353, 485, and 617 — misses of about **195 to 547 years** — instead of
recovering the input age. The correct denominator recovers the input age to within
floating-point precision at every one of those ages.

This is pinned down by a regression guard test,
`test_the_source_documents_denominator_does_not_satisfy_the_identity` in
`backend/tests/estimators/test_kdm.py`, which exercises the real implementation against
the identity (asserting it holds) and separately recomputes the source document's
denominator inline to show it does not recover the age. If anyone ever "fixes" the
implementation back to match the source document's printed formula, this test fails.

That source-research note is retained privately as a historical record and is not
corrected in place. This document, and the code, are the authoritative statement of the
actual formula.

### 8.2 The HRV RMSSD log-linear fit

The original plan proposed fixed HRV-norm coefficients, `ln_intercept = 4.5326` and
`ln_slope = -0.01614`. **These were not the least-squares solution** through the four
normative RMSSD points used to fit them — (25, 60 ms), (45, 43 ms), (55, 34 ms),
(65, 31 ms) — and left a **12.59% residual at age 55**, the worst-fit point:

| Age | Normative RMSSD | Superseded fit residual | Shipped OLS-fit residual |
|---|---|---|---|
| 25 | 60 ms | +3.54% | −0.51% |
| 45 | 43 ms | +4.61% | −1.43% |
| 55 | 34 ms | **+12.59%** (max) | **+5.04%** (max) |
| 65 | 31 ms | +5.08% | −2.92% |

The shipped coefficients, `ln_intercept = 4.517350774886466` and
`ln_slope = -0.017123740486994162` (§4.2, `hrv_norms.yaml`), are the actual OLS fit of
`ln(RMSSD) = ln_intercept + ln_slope · age` over those same four points, computed with
`numpy.polyfit`. Halving the worst-case residual (12.59% → 5.04%) matters here
specifically because that residual is the error the HRV-norm estimator's age inversion
inherits directly — a worse fit at the normative points means a worse age estimate for
any subject whose RMSSD happens to sit near them.

### 8.3 The `steps` query-range cap

An earlier version of this project's ingest layer capped the `steps` data type's query
range at 14 days, based on a bad summarisation of Google's data-types documentation.
**This was wrong.** Per Google's data-types page
(https://developers.google.com/health/data-types, verified 2026-08-02): "The maximum
query range for calories-in-heart-rate-zone, heart-rate, active-minutes, and
total-calories is 14 days. The maximum query range for all other data types is 90 days."
`steps` is not one of those four exceptions, so it uses the same 90-day cap as every
other data type this project reads (§2). `backend/src/bioage/ingest/registry.py` now
documents both the correct cap and the wrong prior assumption in-line, specifically so
the 14-day cap does not get silently reapplied to `steps` by someone "fixing" it back.
