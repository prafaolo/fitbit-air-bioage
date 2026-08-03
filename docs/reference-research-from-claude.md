# Fitbit Air → Biological Age: A Build Guide for a Solo Python Engineer

> **This is the original research brief this project was built from — kept here
> unmodified as a historical record, not corrected in place.** It contains at least
> one documented error that was caught during implementation (the Klemera–Doubal
> denominator formula printed below squares the wrong term; see the corrected
> derivation and a regression test that pins the fix down). Treat everything below as
> an *input to* this project's design, not as documentation *of* the shipped system —
> for the authoritative, corrected account of what the code actually does, see
> [`docs/METHODOLOGY.md`](METHODOLOGY.md), in particular §8, "Corrections to the source
> research and the original plan."

## TL;DR
- **Build on the new Google Health API, not the legacy Fitbit Web API.** The Fitbit Web API is being decommissioned in September 2026; the Google Health API — which Google's release notes (24 Mar 2026) describe as "the next generation of the Fitbit Web API, built from the ground up... focused on achieving parity with the Fitbit Web API across the most requested data types" — is its official successor and the only future-proof path. All the Air's core metrics (HRV, RHR, SpO2, respiratory rate, sleep stages, skin-temperature derivations, steps) are free base-tier data and readable via OAuth scopes without a Premium subscription.
- **The Fitbit Air constrains your model:** it has PPG heart rate, 3-axis accel + gyro, red/IR SpO2, and a skin-temperature sensor — but **no ECG, no GPS, and therefore essentially no usable VO2max**. That kills any true measured-VO2max "Fitness Age" as a directly-measured input. Your reliable signal set is: RHR, nightly HRV (RMSSD), sleep architecture/regularity, daily steps, breathing rate, SpO2, and skin-temp variation.
- **Recommended algorithm: a Klemera–Doubal Method (KDM) biological age computed against NHANES reference parameters, fed with wearable-derived biomarkers (RHR, HRV, steps, sleep, BMI/waist), cross-checked with a non-exercise "Fitness Age" (NTNU/HUNT equation) and a step-count mortality equivalent.** Treat the output as a *fitness/autonomic proxy* with error bars of years, not a validated aging clock. Weight RHR, HRV, and step volume most heavily; treat SpO2 and skin-temp as low-signal trends only.

## Key Findings

### Part 1 — Data extraction
- **Device:** The Google Fitbit Air was announced May 7, 2026, shipped May 26, 2026, at $99.99. It is a screenless 12g band, 7-day battery, water resistant to 50m, Bluetooth 5.0, pairs only with the Google Health app and requires a Google Account. Sensors: optical (PPG) heart rate, 3-axis accelerometer + gyroscope, red + infrared SpO2, device/skin temperature sensor, vibration motor. It stores 7 days of minute-level motion data, 30 days of daily totals, and heart-rate data at 2-second intervals on-device.
- **Metrics it produces:** 24/7 heart rate, resting heart rate, heart rate variability (nightly), SpO2/blood oxygen, breathing (respiratory) rate, skin temperature variation, sleep stages + duration + Sleep Score (new ML model, claimed 15% more accurate), steps/distance/calories, Active Zone Minutes, cardio load, Readiness, AFib/irregular-rhythm notifications.
- **Metrics it LACKS:** No ECG, no GPS (relies on phone assisted-GPS), no NFC. Because VO2max is now computed only from GPS-tracked runs (Google dropped the demographic-based estimate), **the Air effectively does not populate a VO2max/Cardio Fitness Score** unless you manually record phone-GPS runs — multiple users report VO2 Max not showing on the Air.
- **Premium gating:** Core metrics — HRV, RHR, SpO2, breathing rate, sleep stages, Sleep Score, and Readiness — are all **free** on the base (device-paired) tier. Google Health Premium ($9.99/mo, 3-month trial bundled) only unlocks the Gemini-based Health Coach, adaptive plans, and AI interpretation. Notably Readiness became free in Sept 2024 (previously Fitbit Premium-only). Skin temperature is now daily/weekly trends only (minute-level removed for everyone); Sleep Profile, Estimated Oxygen Variation, and stress-score graphs were removed.
- **API longevity — the critical risk assessment:** The legacy **Fitbit Web API is being fully decommissioned in September 2026**; OAuth tokens do not transfer and every user must re-consent. The **Google Health API** (developers.google.com/health) is the official successor, consolidating over 100 legacy endpoints into a streamlined set of ~31 data-type bundles read through uniform methods (`list`, `get`, `reconcile`, `rollUp`, `dailyRollUp`, `patch`, `batchDelete`), on Google Cloud Console + Google OAuth 2.0. The separately-named **Google Fit REST API is also deprecated (no new signups since May 1, 2024; supported only through end of 2026)** — do not confuse it with the Google Health API. Net: build on Google Health API; it is the long-lived path.
- **API access mechanics:** Google Health API read access is free, gated by OAuth scopes (`.../auth/googlehealth.health_metrics_and_measurements.readonly`, `.activity_and_fitness.readonly`, `.sleep.readonly`, etc.), not by any subscription. Relevant data types: `daily-heart-rate-variability`, `daily-resting-heart-rate`, `daily-oxygen-saturation`, `daily-respiratory-rate`, `daily-sleep-temperature-derivations`, `sleep`, `steps`, `heart-rate`, `heart-rate-variability`, `oxygen-saturation`, `vo2-max`/`daily-vo2-max` (likely empty on Air). Query range limits: 14 days for heart-rate/active-minutes/calories; 90 days for other types. There is **no dedicated "readiness" data type** — only its inputs are exposed. Data updates only after the device syncs to the phone (every ~15 min when app open + Bluetooth in range).
- **Legacy Fitbit Web API details (relevant only through Sept 2026 for backfill):** OAuth 2.0 with PKCE; "Personal" app type auto-grants your own intraday data (1-sec/1-min HR, HRV, SpO2, steps) with no special request. Rate limit 150 requests/hour/user. Access tokens live 8 hours; refresh tokens are single-use and never expire until used. Intraday HR limited to 24h per query; time-series can span longer.
- **Python libraries:** `orcasgit/python-fitbit` is effectively abandoned (maintainers publicly discussed the repo being unmaintained; still uses older patterns). `jpstroop/fitbit-client-python` is a modern, fully-typed OAuth2-PKCE client (Python 3.11+). But since both target the *legacy* Fitbit Web API that dies in Sept 2026, and the Google Health API uses standard Google OAuth2 libraries, **the correct choice is to use `google-auth` + `google-auth-oauthlib` + `requests`/`httpx` directly against the Google Health REST endpoints.** `wearipedia` is useful for exploration/simulated data.
- **Google Takeout / export:** A full data export is available (JSON/CSV, granular historical data) but cannot be reliably scheduled — use it once for historical backfill, not for the daily pipeline. Health Connect (Android) is an on-device alternative pipe but is Android/Kotlin-oriented and not a clean Python server-side path; the Google Health API is the server-side equivalent.

### Part 2 — Biological age from wearable data
- **The gold standards (for context only):** DNA-methylation clocks (Horvath, GrimAge, DunedinPACE) and blood-chemistry clocks (Levine PhenoAge, KDM) are what wearable "ages" are validated against. You cannot compute these from a Fitbit; they require methylation arrays or blood panels. But their *math* (KDM, PhenoAge) is directly reusable with wearable-derived biomarkers.
- **Peer-reviewed wearable aging models exist and are strong:**
  - **Pyrkov/Gero (Aging, 2021; Nat Commun 2021):** deep neural nets on step-per-minute streams (GeroSense / DOSI). Trained on 103,830 one-week + 2,599 up-to-2-year samples; biological-age acceleration from steps predicts mortality comparably to blood-based BAA. Key insight: aging manifests as slower recovery (loss of resilience), doubling every ~8 years matching the Gompertz law.
  - **MoveAge (McIntyre et al.):** ML on NHANES 2003–2006 accelerometry predicting biological age; deltaAge associates with all-cause mortality.
  - **CosinorAge (Barata et al., *npj Digital Medicine* 2024;7:146, Centre for Digital Health Interventions, ETH Zurich):** a circadian-rhythm accelerometry biomarker "developed from wearable-derived circadian rhythmicity from 80,000 midlife and older adults in the UK and US. A one-year increase in CosinorAge corresponded to 8–12% higher all-cause and cause-specific mortality risks"; it "correlated with both KDM BA and PhenoAge with r = 0.87 (KDM, p < 0.001) and r = 0.81 (PhenoAge, p < 0.001)." **Has an open-source Python package.**
  - **PpgAge (Miller et al., "A wearable-based aging clock associates with disease and behavior," *Nature Communications* 2025, s41467-025-64275-4):** deep learning on wrist PPG from the Apple Heart & Movement Study (213,593 participants; >149 million participant-days). It predicts chronological age with "MAE of 2.43 years (95% CI 2.33–2.53)" in a healthy cohort (n=6,728), ~3.2 yr in the general population; the PpgAge gap predicts incident cardiovascular disease (HR ≈ 1.46) and captures sleep, exercise, and pregnancy effects. Proof that PPG carries aging signal, but the model is not released for Fitbit.
- **Component equations you can implement yourself:**
  - **NTNU/HUNT non-exercise "Fitness Age" (Nes et al. 2011, *Scand J Med Sci Sports*; HUNT Fitness Study, n=3,320):** VO2max (men) = 100.27 − 0.296×age + 0.226×PA − 0.369×WC − 0.155×RHR; (women) = 74.74 − 0.247×age + 0.198×PA − 0.259×WC − 0.114×RHR (PA = physical activity score, WC = waist circumference in cm, RHR = resting HR). Garmin licenses this. Crucially it *doesn't need a measured VO2max* — it's a non-exercise estimate from age/sex/RHR/waist/activity, all of which the Air can supply. SEE ≈ ±3.5 ml/kg/min.
  - **HRV normative decline:** RMSSD declines ~1–3%/year after the mid-20s; approximate nightly RMSSD medians ~60ms (25y) → ~43ms (40s) → ~34ms (50s) → ~31ms (60s). Invert measured RMSSD against age-sex norms to get an "HRV age." Strong caveat: Fitbit computes HRV only during sleep, and consumer PPG HRV is noisier than ECG.
  - **RHR** rises with age and predicts mortality; use as a KDM biomarker.
  - **Sleep markers:** sleep efficiency, WASO, deep/REM proportions, and especially **sleep regularity** decline/shift with age.
  - **Step-count mortality (Paluch et al., *Lancet Public Health* 2022;7(3):e219–e228):** a meta-analysis of 15 cohorts totalling 47,471 adults with 3,013 deaths (10.1 per 1000 participant-years) found "Taking more steps per day was associated with a progressively lower risk of all-cause mortality, up to a level that varied by age." Convert your step volume into a mortality-hazard-equivalent age.
- **Combining into one number:**
  - **KDM (Klemera–Doubal)** is the recommended core: regress each biomarker on chronological age in a reference population (NHANES), then invert to find the age at which your biomarker profile is "normal." Implemented in the R `BioAge` package (Kwon & Belsky, *GeroScience* 2021;43:2795–2808) — you can port the math or call it via `rpy2`.
  - **PhenoAge (Levine 2018)** uses a Gompertz mortality model; its exact coefficients are published (see Details). It requires blood markers you don't have, but the *framework* can be re-fit.
  - **Homeostatic dysregulation (Mahalanobis distance)** is a third option, also in `BioAge`.
  - `pyaging` is a Python package of 30+ aging clocks but is methylation/omics-focused, not wearable inputs. `CosinorAge` is the one Python package that directly takes wearable accelerometry.
- **Reliability — be honest:** Fitbit HR is accurate at rest/sleep (a Fitbit Charge HR polysomnography validation found mean difference −0.66 bpm and overall r≈0.93, higher during sleep). But consumer wrist PPG HRV is meaningfully less accurate than ECG: in a 2025 ECG-referenced validation (Dial et al.), finger/ring devices (Oura Gen 4 CCC=0.99) and Whoop (CCC=0.94) beat wrist devices, and wrist HRV MAPE often exceeds 10%, worse in older users. Sleep-stage accuracy is moderate (Cohen's κ ~0.4). So: most wearable "ages" are fitness/autonomic proxies, not validated aging clocks; expect error bars of several years and meaningful test–retest noise. Weight RHR, HRV trend, and step volume most; treat single-night SpO2 and skin-temp as noise, using only multi-week trends.

## Details

### 1a. The device and its data
The Fitbit Air is Google's screenless, subscription-optional tracker. Its sensor suite (optical HR, 3-axis accel+gyro, red/IR SpO2, temperature sensor) produces: continuous HR, RHR, nightly HRV, SpO2, breathing rate, skin-temperature variation, sleep stages + Sleep Score, steps/distance/calories/AZM, cardio load, Readiness, and AFib notifications. It lacks ECG and GPS. VO2max is not reliably generated because Google now derives it only from GPS-tracked runs. All the metrics you need for a biological-age model are in the free base tier; Premium only adds AI coaching.

For the biological-age use case this means your usable inputs are: **RHR, nightly RMSSD HRV, sleep architecture + regularity, daily step count, breathing rate, SpO2 trend, skin-temp variation trend**, plus self-entered height/weight/waist and age/sex.

### 1b. Data access paths
**Google Health API (the answer).** Launched March 24, 2026; official successor to the Fitbit Web API. Setup: create a Google Cloud project, enable the Google Health API, configure the OAuth consent screen, add the needed scopes, create OAuth 2.0 credentials. Uses standard Google OAuth2 libraries. Read scopes are per-domain (health_metrics_and_measurements, activity_and_fitness, sleep, ecg, etc.). Data types are read via uniform list/get/reconcile/rollup/dailyRollup methods. Rate limits are enforced per-minute/daily/per-user with 429 on exceed; defaults are generous for a personal n=1 pull. No subscription required for API reads.

**Legacy Fitbit Web API (backfill only, dies Sept 2026).** OAuth 2.0 + PKCE; "Personal" app type gives automatic access to your own intraday data. 150 req/hr/user. 8-hour access tokens; single-use refresh tokens.

**Google Takeout:** one-time historical backfill (JSON/CSV), not automatable.

**Health Connect:** Android on-device; not a clean Python server path.

**Reverse-engineered/unofficial mobile-app endpoints:** exist but violate ToS and are fragile — do not use as primary.

### 1c. Recommended pipeline
Authenticate once via Google OAuth2 (installed-app / loopback flow), persist the refresh token, and run a daily job (cron or GitHub Actions) that refreshes the access token, pulls the previous day's data types, and writes to SQLite/Parquet. A meaningful advantage over the legacy Fitbit API: Google's refresh tokens are reusable, so unattended scheduling is far simpler than Fitbit's single-use refresh-token dance.

```python
# pip install google-auth google-auth-oauthlib requests
import json, sqlite3, datetime as dt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import requests

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
]
TOKEN_FILE = "token.json"
BASE = "https://healthapi.googleapis.com/v4/users/me"  # verify exact host in live docs

def get_creds():
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except FileNotFoundError:
        pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds

def pull(creds, data_type, start, end):
    h = {"Authorization": f"Bearer {creds.token}"}
    params = {"filter": f'start_time>="{start}" AND start_time<"{end}"'}
    r = requests.get(f"{BASE}/dataTypes/{data_type}/dataPoints", headers=h, params=params)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    creds = get_creds()
    today = dt.date.today()
    start, end = str(today - dt.timedelta(days=2)), str(today)
    con = sqlite3.connect("fitbit_air.db")
    con.execute("CREATE TABLE IF NOT EXISTS raw(dtype TEXT, day TEXT, payload TEXT)")
    for dtp in ["daily-resting-heart-rate", "daily-heart-rate-variability",
                "steps", "sleep", "daily-respiratory-rate",
                "daily-oxygen-saturation", "daily-sleep-temperature-derivations"]:
        data = pull(creds, dtp, start, end)
        con.execute("INSERT INTO raw VALUES (?,?,?)", (dtp, start, json.dumps(data)))
    con.commit(); con.close()
```

Schedule via GitHub Actions (store `client_secret.json` and `token.json` as encrypted secrets; because Google refresh tokens are reusable, you can persist the token in a secret store or re-commit it, and the job runs unattended indefinitely). Confirm the exact API host and `filter`/pagination syntax against the live reference at build time — the API is new and Google warned of breaking changes through late May 2026.

### 2. Biological age — recommended approach

**Step 1 — Assemble a biomarker vector** (30-day medians to beat noise): RHR, nightly RMSSD, mean daily steps, sleep efficiency, sleep regularity, breathing rate, plus age/sex/BMI/waist.

**Step 2 — Compute two independent estimates:**
1. **KDM biological age** using NHANES reference regressions for the biomarkers you have (RHR, BMI/waist, plus any lab you self-supply). Port `BioAge::kdm_calc` logic or call via `rpy2`.
2. **Non-exercise Fitness Age** via the NTNU/HUNT VO2max equation → map VO2max to the age at which your value equals the population median.

**Step 3 — Cross-check with a step-count mortality-equivalent age** (Paluch dose–response) and an HRV-norm age.

**Step 4 — Report a range, not a point estimate**, and track the *trend* over months — the trend is far more reliable than any absolute number.

### KDM math
For each biomarker j, regress on chronological age in the reference sample: x_j = q_j + k_j·age + s_j (residual SD). The Klemera–Doubal estimator without the chronological-age term is:

BA_E = [ Σ_j (x_j − q_j)(k_j / s_j²) ] / [ Σ_j (k_j / s_j²)² ]

then optionally corrected toward chronological age using the characteristic variance s_BA². The Klemera–Doubal 2006 paper and the `BioAge` package give the exact closed form and NHANES-derived q_j, k_j, s_j.

### PhenoAge coefficients (for reference / if you add self-supplied bloods)
Levine 2018 (corrected equation): xb = −19.907 − 0.0336×albumin + 0.0095×creatinine + 0.1953×glucose + 0.0954×ln(CRP) − 0.0120×lymphocyte% + 0.0268×MCV + 0.3306×RDW + 0.00188×alkaline_phosphatase + 0.0554×WBC + 0.0804×age; M = 1 − exp(−1.51714·exp(xb)/0.0076927); PhenoAge = 141.50 + ln(−0.00553·ln(1−M)) / 0.09165. These require blood markers the Air cannot provide, but the Gompertz-inversion framework is a template if you ever add lab data.

## Recommendations
1. **First, migrate your mental model to the Google Health API.** Register a Google Cloud project now, enable the Health API, complete OAuth, and confirm you can pull `daily-resting-heart-rate` and `sleep`. Benchmark: a successful authenticated pull of 7 days of RHR + sleep.
2. **Build the ingestion MVP** (the code above) → SQLite. Backfill history once via Google Takeout.
3. **Build the biomarker layer**: 30-day rolling medians of RHR, RMSSD, steps, sleep efficiency/regularity.
4. **Implement two estimators**: NTNU Fitness Age (trivial, closed-form) first, then KDM against NHANES. Ship Fitness Age as v1 because it needs only RHR + waist + activity + age/sex — all available day one.
5. **Add CosinorAge** if you can obtain minute-level accelerometry (harder on the Air, which exposes steps not raw accel via API — this may be infeasible; treat as a stretch goal, or approximate circadian rhythm from minute-level steps/HR).
6. **Report trends, weight RHR/HRV/steps most**, and annotate every number with its error bar.

**Thresholds that change the plan:** If VO2max never populates (expected on Air), drop any measured-VO2max path and rely on the non-exercise equation. If nightly HRV proves too noisy (test–retest swings >15–20%), downweight it and lean on RHR + steps + sleep regularity. If Google exposes a raw-accelerometry or intraday endpoint for the Air, add CosinorAge as your best-validated wearable clock.

## Caveats
- A Fitbit-only "biological age" is a **fitness/autonomic proxy**, not a validated aging clock; treat absolute values with skepticism and focus on longitudinal change.
- Consumer wrist PPG HRV is materially less accurate than ECG; the Air is likely similar to other wrist devices (worse than Oura/Whoop finger/strap sensors).
- The Air produces no ECG and effectively no VO2max — several published wearable-age methods (PpgAge, measured-VO2max fitness age) are therefore not directly usable; PpgAge in particular is proprietary to Apple and unreleased.
- NHANES accelerometry (2003–2006 uniaxial; 2011–2014 wrist triaxial at 80Hz in MIMS units) differs from Fitbit's processed outputs — reference-population and sensor mismatch add error to any NHANES-trained model.
- The exact Google Health API hostname/endpoint shapes and rate-limit numbers should be verified against the live docs at build time, as the API is new (2026) and Google warned of breaking changes through late May 2026. Commercial "ages" (Garmin Fitness Age, Oura Cardiovascular Age, Whoop Age) mostly do not publish full, independently-validated methodology — do not treat them as ground truth.