# LDN Planning — Scenario Tool Methodology

**Scope.** This note documents the *scientific methodology* behind the LDN Planning **Scenario &
BAU Projection** tool — how planned interventions are spatialized, how the anticipatory balance
sheet of gains and avoided losses is computed, and how the scenario is evaluated against the
Business‑As‑Usual trajectory over a user‑specified planning horizon. It deliberately describes the
*approach and its assumptions*, not the implementation. For the broader feature set and delivery
plan see [LDN_PLANNING_TOOL_MVP_PLAN.md](LDN_PLANNING_TOOL_MVP_PLAN.md).

**Conceptual basis (authoritative).**

- Cowie, A.L., et al. (2018). *Land in balance: The scientific conceptual framework for Land
  Degradation Neutrality.* Environmental Science & Policy 79: 25–35.
- UNCCD (2025). *Good Practice Guidance (GPG) Addendum for SDG Indicator 15.3.1* (Advanced Unedited
  Version).

---

## 1. Purpose and the planning question

The Scenario tool answers a forward‑looking planning question:

> *If a set of interventions (protect / manage / restore) were implemented across chosen areas, at
> plausible levels of effectiveness, what is the anticipated contribution toward Land Degradation
> Neutrality (LDN) — and where?*

Neutrality is assessed as an **area‑based balance of gains against losses within each land type**
(Cowie et al. 2018). In *planning* mode this balance is **anticipatory**: it projects the gains a
plan is expected to generate and the losses it is expected to prevent, using the same gains/losses
accounting logic that monitoring applies retrospectively.

---

## 2. The response hierarchy and what each intervention can claim

Interventions are typed by the LDN response hierarchy **Avoid > Reduce > Reverse** (Cowie et al.
2018, Principle 12). The methodology enforces a strict, non‑negotiable distinction in what each
response is allowed to contribute to the balance sheet:

| Response | Target land condition | Mechanism | Balance‑sheet role |
|---|---|---|---|
| **Avoid** | Healthy / non‑degraded | Protect from anticipated future degradation | **Avoided loss** (not a gain) |
| **Reduce** | At‑risk / stressed but not yet degraded | SLM slows or halts ongoing decline | **Avoided loss** (not a gain) |
| **Reverse** | Already degraded | Restoration / rehabilitation | **Counterbalancing gain** |

The single most important accounting rule (Cowie et al. 2018): **only *Reverse* generates the gains
in land‑based natural capital that can counterbalance losses.** *Avoid* and *Reduce* prevent or slow
losses but do **not**, by themselves, create counterbalancing gains. The tool keeps *gains* and
*avoided losses* in separate columns throughout, precisely to prevent the common misconception that
avoidance or reduction alone can deliver neutrality.

The eligible land condition for each response is taken from the **Avoid / Reduce / Reverse (ARR)
classification** layer, which reclassifies the SDG 15.3.1 status into the three response classes
under the "one‑out, all‑out" (1OAO) rule. A pixel can only receive a given intervention where its
ARR class matches (e.g. *Reverse* effects are only credited on degraded pixels).

---

## 3. Expected‑value spatialization (the core method)

### 3.1 Why not simply flip pixels?

A naïve scenario tool would deterministically switch a chosen set of pixels from "degraded" to
"improved". This is scientifically fragile: it forces an all‑or‑nothing outcome, gives no sense of
*where* success is more or less likely, hides the effect of partial effectiveness, and makes the
resulting area totals sensitive to arbitrary pixel choices.

Instead, the tool uses an **expected‑value model**. Effectiveness is treated as a **probability of
successful treatment** applied at the pixel level, and the reported areas are **statistical
expectations** rather than deterministic counts.

### 3.2 Per‑pixel probability surfaces

For each target polygon the planner specifies an intervention type and an **effectiveness**
$e \in [0, 1]$. Every eligible pixel that the polygon covers is assigned a probability of being
successfully treated equal to that effectiveness. Where target polygons overlap, the pixel keeps the
**maximum** probability across the overlapping targets (a pixel is treated at least as well as the
best plan covering it):

$$
p(x) = \max_{\,t \,:\, x \in t \text{ and } x \text{ eligible for } t}\; e_t
$$

This produces three continuous **probability surfaces**, one per response, each defined only over its
eligible ARR class:

- $p_{\text{reverse}}(x)$ over degraded (*Reverse*) pixels — probability of restoration success;
- $p_{\text{reduce}}(x)$ over at‑risk (*Reduce*) pixels — probability that decline is averted;
- $p_{\text{avoid}}(x)$ over healthy (*Avoid*) pixels — probability that the pixel is protected.

Pixels outside a response's eligible class are marked "no data" for that surface; eligible but
untargeted pixels carry probability 0. These three surfaces are the tool's spatial output and can be
mapped directly to show *where* the plan is expected to act and *how likely* success is.

### 3.3 From probability to expected area

Because each pixel carries a known ground area $a(x)$ (computed from the pixel's geodesic size), the
**expected treated area** for a response is the probability‑weighted sum of pixel areas over its
eligible class $C$:

$$
\mathbb{E}[A_{\text{response}}] = \sum_{x \in C} a(x)\, p_{\text{response}}(x)
$$

This is the expectation of a sum of independent Bernoulli‑weighted areas. It is exact (no
simulation needed) and additive, so it can be integrated over any spatial grouping simply by summing
the same per‑pixel expected‑area contributions within that group (see §4).

The three response totals map onto the balance sheet per §2:

$$
\text{gains} = \mathbb{E}[A_{\text{reverse}}], \qquad
\text{avoided losses} = \mathbb{E}[A_{\text{reduce}}] + \mathbb{E}[A_{\text{avoid}}]
$$

### 3.4 Interpreting the numbers

- The expected areas are **planning estimates**, not guarantees; they answer "on average, how much
  area would this plan be expected to restore / protect?"
- Because the model is linear in probability, halving effectiveness halves the expected contribution
  — the balance sheet responds transparently and monotonically to the planner's assumptions.
- Effectiveness values are exposed as visible, documented, editable inputs so that every number on
  the balance sheet is traceable to a stated assumption.

---

## 4. Accounting dimensions: land type and jurisdiction

Neutrality must be judged **"like for like" within land types** defined by land potential, mapped at
the baseline and held fixed. A gain in one land type cannot offset
a loss in another. Because the per‑pixel expected‑area contributions of §3.3 are additive, the tool
integrates them over two independent grouping layers:

1. **By land type** — using a land‑type raster (a baseline land cover map is the accepted default
   proxy where no land‑potential map exists). Reporting per land type is what makes the balance sheet
   compatible with the LDN “like for like” requirement. The land‑type raster may alternatively be a
   **saved land types layer** produced by the *Define Land Types* tool (see below), which allows any
   combination of categorical rasters — land cover, land potential, administrative codes — to define
   the land types jointly.
2. **By jurisdiction** — using administrative units (level 1) or an uploaded polygon layer, so
   results can be attributed to the governance units that will actually plan and implement.

Each grouping yields its own balance sheet (gains, avoided losses by response, and totals per group),
reported on a separate sheet. National totals are the ungrouped sums. Because all three views derive
from the *same* per‑pixel expected areas, they are internally consistent (the group rows sum to the
national totals).

**Defining land types.** The land‑type input for the balance sheet may be (a) a standard SDG
15.3.1 land cover layer (selected from previously computed datasets) or (b) a **saved land types
layer** built with the *Define Land Types* tool. That tool combines one or more categorical rasters
(land cover, land potential, administrative codes, …) into a single raster where **each unique
combination of the inputs’ class values becomes one land type** — the same “spatial unit”
construction used by LDN Counterbalancing. The tool processes the data block‑by‑block with an
adaptive block height so that it remains memory‑safe for any input size, including country‑scale
analyses at 30 m resolution (e.g. Brazil). Saved land types layers are **reusable across analyses**
(this tool and Counterbalancing) without recomputation, ensuring every analysis partitions space
identically and consistently.

**Defining jurisdictions.** Jurisdiction layers — used for the separate per‑jurisdiction balance
sheet — may be (a) administrative units (level 1) of the selected country, fetched automatically,
or (b) an uploaded polygon layer. The jurisdiction breakdown is independent of the land‑type
breakdown: both can be produced from the same run, and both derive from the same per‑pixel
expected areas, so their rows are internally consistent with each other and with the national totals.

---

## 5. Comparison against BAU over the planning horizon

A scenario is only meaningful against a counterfactual and a time frame. The tool therefore couples
the scenario with a **Business‑As‑Usual (BAU)** projection over a user‑specified horizon
($t_0 \to$ target year):

- The BAU trajectory is derived from the change in degraded area between the baseline and reporting
  periods, extrapolated linearly to the target year (the LDN frame of reference sets the **target =
  baseline** degraded area — no net loss; Cowie et al. 2018, Module B).
- The scenario's **gains** (Reverse) and **avoided losses** (Avoid + Reduce) are subtracted from the
  BAU‑projected degraded area to give a **scenario‑adjusted degraded area** at the target year:

$$
D_{\text{scenario}}(t) = \max\!\big(0,\; D_{\text{BAU}}(t) - \text{gains} - \text{avoided losses}\big)
$$

- **Neutrality is achieved** for the horizon when $D_{\text{scenario}}(t) \le D_{\text{baseline}}$
  (the LDN target). The tool reports the BAU shortfall above target, the share of that shortfall the
  plan closes, and the remaining shortfall — nationally and, where jurisdiction layers are supplied,
  per jurisdiction. The BAU trajectory is also broken down per land type (matching the scenario
  breakdown) so that the gain‑versus‑loss accounting can be inspected land‑type by land‑type over
  the planning horizon.

This makes explicit that avoidance/reduction act on the *future* (they bend the BAU curve) while
restoration gains act on the *existing* degraded stock, and that both must be judged against the
baseline over the chosen period.

---

## 6. Assumptions and limitations (current phase)

The method is deliberately transparent about where it simplifies:

1. **Avoided losses are an upper bound.** *Avoid* and *Reduce* credit is currently computed as the
   expected treated area of healthy/at‑risk land, i.e. it implicitly assumes that **all** of that land
   *would otherwise have degraded* under business‑as‑usual (BAU). In reality only a fraction of
   healthy/at‑risk land degrades in any planning horizon, so true avoided losses are lower. The
   avoided‑losses figures should therefore be read as an optimistic ceiling, and are labelled as such
   in the outputs. (Weighting by BAU risk is the Phase 2 refinement — §7.)
2. **Effectiveness is a single scalar per target.** A flat probability is applied uniformly across a
   target, independent of biophysical suitability, accessibility or cost. Spatially varying
   suitability is a Phase 2 refinement.
3. **Independence and analytic expectation.** The expected areas are analytic expectations that do not
   propagate uncertainty into a distribution; there are no confidence intervals yet. A Monte Carlo
   ensemble (Phase 3) would provide them.
4. **Land type as land‑cover proxy.** Where a land‑potential map is unavailable, baseline land cover
   is used as the proxy for land type, consistent with GPG guidance, but it is a proxy.
5. **Grouping‑layer alignment.** Land‑type and jurisdiction layers are resampled/rasterized onto the
   ARR analysis grid; very coarse or misaligned inputs will blur group boundaries.

None of these simplifications affect the *gains vs. avoided‑losses* separation, which is enforced
unconditionally.

---

## 7. Planned methodological refinements

The spatialization is designed to be tightened in stages without changing its outputs' meaning:

- **Phase 1 (current) — expected‑value spatialization.** Per‑pixel probability surfaces and expected
  areas; gains vs. avoided losses; national, per‑land‑type and per‑jurisdiction balance sheets;
  avoided losses as an upper bound.
- **Phase 2 — risk‑ and suitability‑weighting.** (a) Weight *avoided losses* by an explicit per‑pixel
  **BAU degradation‑risk surface** (derived from the historical BAU trajectory and/or pressure/driver
  layers) so that only the fraction of land genuinely expected to degrade is credited — replacing the
  upper‑bound assumption with a risk‑adjusted estimate. (b) Weight the per‑pixel treatment probability
  by **intervention suitability** (biophysical/land‑potential fit, accessibility, cost) instead of a
  single flat effectiveness.
- **Phase 3 — Monte Carlo uncertainty.** Replace the analytic expectation with an ensemble of
  realizations (per‑pixel Bernoulli draws over many runs) to produce full probability distributions
  and confidence intervals on every balance‑sheet figure.

---

## 8. Relationship to counterbalancing (neutrality check)

The scenario balance sheet is an *anticipatory* application of the same accounting used by the LDN
**Counterbalancing** module. Reverse‑driven gains feed the "gains" side and Avoid/Reduce feed the
"avoided losses" side; the per‑land‑type structure preserves the "like for like" rule; and neutrality
for a land type is achieved when its anticipated gains at least offset its anticipated losses, with
overall neutrality achieved only when **every** land type is neutral (1OAO at the land‑type level).
The scenario tool thus lets planners iterate on interventions *before* committing, and hand the
resulting targets to the counterbalancing check for the formal neutrality assessment.

Note on land types: both this tool and the LDN Counterbalancing module **consume the same saved
land types layer** produced by the *Define Land Types* tool. Creating the land types layer once and
reusing it ensures that the spatial units are identical across the planning scenario and the
counterbalancing assessment, which is a requirement of the “like for like” accounting rule (§4).
The land types layer does not need to be re‑created for each analysis.

---

## 9. References

- Cowie, A.L., Orr, B.J., Castillo Sanchez, V.M., Chasek, P., Crossman, N.D., Erlewein, A., Louwagie,
  G., Maron, M., Metternicht, G.I., Minelli, S., Tengberg, A.E., Walter, S., Welton, S. (2018).
  *Land in balance: The scientific conceptual framework for Land Degradation Neutrality.*
  Environmental Science & Policy 79: 25–35.
- UNCCD (2025). *Good Practice Guidance Addendum for SDG Indicator 15.3.1* (Advanced Unedited
  Version).
- Sims, N.C., et al. *Good Practice Guidance: SDG Indicator 15.3.1, Proportion of Land That Is
  Degraded Over Total Land Area* (UNCCD), for the underlying status/one‑out‑all‑out accounting.
