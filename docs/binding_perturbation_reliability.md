# Reliability and Spearman's Correction: Binding vs. Perturbation

Adapted from: Csardi et al (2015), *PLOS Genetics*.
DOI: [10.1371/journal.pgen.1005206](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1005206)

**NOTE**: this is produced with the help of Claude, and was provided the above
paper as input along with the prompt: focusing specifically on the reliability
and spearman correlation equations presented in the methods section, adapt 
the authors' framework for estimating the reliability of mRNA and protein measurements
and correcting the observed correlation between them to the case of TF binding and TF
perturbation datasets. The AI output was revised/edited by a human.

---

## 1. Binding and perturbation datasets have low observed correlation

When we compare a transcription factor's binding profile to its perturbation
profile, we are implicitly asking: how well does physical occupancy at a
promoter predict the transcriptional effect of removing or depleting the
factor? Any observed correlation $r_{XY}$ between binding scores and
perturbation effect sizes is *attenuated* relative to the true underlying
relationship, because both measurements carry independent noise.

The Csardi et al. framework formalizes this attenuation and provides a
correction. The original paper applied it to mRNA abundance vs. protein
abundance. The adaptation here maps the same equations onto TF binding
data and TF perturbation data.  

We use their framework to ask, "How much do the low observed correlations between 
binding and perturbation reflect noise in the measurements, and how much reflects
genuine biological complexity (e.g. condition-specific regulation, indirect effects)?"  

The original authors made use of "Model II regression" with the package
[lmod2](https://cran.r-project.org/web/packages/lmodel2/index.html) in R.

---

## 2. Original Framework (mRNA vs. Protein)

### 2.1 Measurement Model

For a gene $g$, let $\phi_g$ be its true mRNA level and $\psi_g$ its true
protein level. We observe noisy surrogates:

$$X_g = \phi_g + \varepsilon_X, \qquad Y_g = \psi_g + \varepsilon_Y \tag{1}$$

where $\varepsilon_X$ and $\varepsilon_Y$ are zero-mean noise terms,
uncorrelated with the signal and with each other.

### 2.2 Reliability

The *reliability* of measurement $X$ is the fraction of observed variance
that is signal:

$$\alpha_X = \frac{\mathrm{Var}(\phi)}{\mathrm{Var}(X)} = \frac{\mathrm{Var}(\phi)}{\mathrm{Var}(\phi) + \mathrm{Var}(\varepsilon_X)} \tag{2}$$

Given two replicate measurements $X_1, X_2$ of the same latent variable
$\phi$ (both with independent noise), the Pearson correlation between them
is the *geometric mean* of their reliabilities:

$$\rho_{X_1 X_2} = \sqrt{\alpha_{X_1}\,\alpha_{X_2}} \tag{3}$$

This holds because noise terms cancel in the covariance but inflate the
individual variances. When the two replicates are drawn from the same
measurement process, $\alpha_{X_1} = \alpha_{X_2} = \alpha_X$, so
$\rho_{X_1 X_2} = \alpha_X$.

### 2.3 Attenuation of the Cross-Modal Correlation

The observed Pearson correlation between the noisy measurements $X$ and $Y$
is related to the true latent correlation $\rho_{\phi\psi}$ by:

$$\rho_{XY} = \rho_{\phi\psi} \cdot \sqrt{\alpha_X \cdot \alpha_Y} \tag{4}$$

Because $\alpha_X, \alpha_Y \in (0, 1]$, the observed correlation is always
pulled toward zero. The true correlation is recovered by dividing out the
attenuation factor.

### 2.4 Spearman's Correction (two replicates each)

With one replicate of each type ($X_1, X_2$ for the first modality and
$Y_1, Y_2$ for the second), the corrected estimate is:

$$\hat{\rho}_{\phi\psi} = \frac{\rho_{X_1 Y_1}}{\sqrt{\rho_{X_1 X_2} \cdot \rho_{Y_1 Y_2}}} \tag{5}$$

or, using all four cross-modal pairings to reduce variance:

$$\hat{\rho}_{\phi\psi} = \frac{\left(\rho_{X_1 Y_1}\,\rho_{X_1 Y_2}\,\rho_{X_2 Y_1}\,\rho_{X_2 Y_2}\right)^{1/4}}{\sqrt{\rho_{X_1 X_2} \cdot \rho_{Y_1 Y_2}}} \tag{6}$$

### 2.5 Extension to $N$ Binding and $M$ Perturbation Datasets

With $N$ independent binding datasets and $M$ independent perturbation
datasets, the general estimator uses the geometric means of all
within-modality and cross-modality pairwise correlations:

$$\hat{\rho}_{\phi\psi} =
\frac{\displaystyle\left(\prod_{i=1}^{N}\prod_{j=1}^{M} r_{X_i Y_j}\right)^{\!\!\frac{1}{NM}}}
{\sqrt{\displaystyle\left(\prod_{i < i'} r_{X_i X_{i'}}\right)^{\!\!\frac{2}{N(N-1)}} \cdot \left(\prod_{j < j'} r_{Y_j Y_{j'}}\right)^{\!\!\frac{2}{M(M-1)}}}}
\tag{7}$$

The denominator is the geometric mean of the within-binding pairwise
correlations times the geometric mean of the within-perturbation pairwise
correlations, i.e. the square root of the product of the two reliability
estimates.

---

## 3. Adaptation to Binding vs. Perturbation

### 3.1 Re-mapping the Variables

| Original | Binding-Perturbation | Interpretation |
|---|---|---|
| $\phi_g$ | $\phi_{kg}$ | True binding affinity of TF $k$ at promoter of gene $g$ |
| $\psi_g$ | $\psi_{kg}$ | True regulatory effect of TF $k$ on expression of gene $g$ |
| $X_g$ | $X_{kg}$ | Observed binding score (enrichment, ChIP ratio, etc.) |
| $Y_g$ | $Y_{kg}$ | Observed perturbation effect size (log$_2$FC, etc.) |
| $\rho_{\phi\psi}$ | $\rho_{\phi\psi}^{(k)}$ | True binding-to-perturbation coupling for TF $k$ |

The measurement model is identical. Binding scores carry assay-specific
noise (PCR amplification biases, transposon insertion preferences, antibody
cross-reactivity), and perturbation effect sizes carry independent noise
(batch effects, incomplete depletion, indirect effects).

### 3.2 Unit of Analysis and the Correlation Vector

For a fixed TF $k$, the binding score vector over all $G$ target genes is:

$$\mathbf{X}^{(k)} = \bigl(X_{k,1},\, X_{k,2},\, \ldots,\, X_{k,G}\bigr)$$

and the perturbation effect vector is:

$$\mathbf{Y}^{(k)} = \bigl(Y_{k,1},\, Y_{k,2},\, \ldots,\, Y_{k,G}\bigr)$$

All pairwise correlations below (e.g. $r_{X_i X_{i'}}$ for TF $k$) are
Pearson or Spearman correlations computed over genes $g = 1, \ldots, G$,
restricted to genes with non-missing values in both datasets.

The observed binding-perturbation correlation for TF $k$ is

$$r_{XY}^{(k)} = \mathrm{corr}\!\left(\mathbf{X}^{(k)},\, \mathbf{Y}^{(k)}\right)$$

and the corrected estimate $\hat{\rho}^{(k)}_{\phi\psi}$ answers: "What
would this correlation be if both measurements were perfectly reliable?"

### 3.3 Available Datasets

**Binding datasets ($X_i$):**

| Symbol | Dataset | Score column | Technology |
|---|---|---|---|
| $X_1$ | `callingcards` | `callingcards_enrichment` | Transposon calling cards |
| $X_2$ | `harbison` | `effect` (YPD condition) | ChIP-chip |
| $X_3$ | `rossi` | `enrichment` | ChIP-exo |
| $X_4$ | `chec_m2025` | `enrichment` | ChEC-seq |

**Perturbation datasets ($Y_j$):**

| Symbol | Dataset | Score column | Technology |
|---|---|---|---|
| $Y_1$ | `kemmeren` | `M` | Microarray, gene deletion |
| $Y_2$ | `hughes_knockout` | `mean_norm_log2fc` | Two-colour array, deletion |
| $Y_3$ | `degron` | `log2FoldChange` | RNA-seq, auxin degron |

---

## 4. Reliability Estimation for Each Modality

### 4.1 Binding Reliability

For TF $k$ that is measured in both dataset $X_i$ and dataset $X_{i'}$,
the pairwise reliability estimate is:

$$\hat{\alpha}_{X}^{(k)}\bigl(i, i'\bigr) = r_{X_i^{(k)},\, X_{i'}^{(k)}} \tag{8}$$

When more than two binding datasets cover TF $k$, take the geometric mean
over all $\binom{N}{2}$ pairs:

$$\hat{\alpha}_{X}^{(k)} = \left(\prod_{i < i'} r_{X_i^{(k)},\, X_{i'}^{(k)}}\right)^{\!\!\frac{2}{N(N-1)}} \tag{9}$$

In practice, with the datasets listed above, the usable pairings for a
given TF depend on coverage (102 TFs shared between `callingcards` and
`harbison`; 777 in `rossi` but fewer in older datasets). If only one pair
is available, Eq. 8 is used directly.

**Important caveat:** Unlike the original paper, where replicates represent
the same protocol applied twice, here $X_i$ and $X_{i'}$ represent
*different assay technologies* (calling cards, ChIP-chip, ChIP-exo,
ChEC-seq). The cross-technology correlation is therefore a *lower bound*
on true reliability: it conflates measurement noise with systematic
between-technology biases. The corrected $\hat{\rho}_{\phi\psi}$ will
accordingly be a *conservative* upper bound on the true binding-perturbation
coupling.

### 4.2 Perturbation Reliability

Analogously, for TF $k$ measured in perturbation datasets $Y_j$ and
$Y_{j'}$:

$$\hat{\alpha}_{Y}^{(k)}\bigl(j, j'\bigr) = r_{Y_j^{(k)},\, Y_{j'}^{(k)}} \tag{10}$$

With all three perturbation datasets:

$$\hat{\alpha}_{Y}^{(k)} = \left(\prod_{j < j'} r_{Y_j^{(k)},\, Y_{j'}^{(k)}}\right)^{\!\!\frac{1}{3}} \tag{11}$$

The 51 TFs shared between `kemmeren` and `hughes_knockout` can supply
$\hat{\alpha}_Y$ estimates; `degron` uses a different depletion mechanism
(auxin-inducible degron, RNA-seq) which may introduce additional
between-technology variance relative to within-deletion-study variance.

---

## 5. Corrected Binding-Perturbation Correlation

### 5.1 Two-Dataset Version (one binding, one perturbation)

With a single binding dataset $X$ and a single perturbation dataset $Y$
for TF $k$, no within-modality reliability estimate is possible from the
data alone. The correction requires an externally estimated reliability
or a pooled estimate computed across all TFs:

$$\hat{\rho}_{\phi\psi}^{(k)} = \frac{r_{XY}^{(k)}}{\sqrt{\bar{\alpha}_X \cdot \bar{\alpha}_Y}} \tag{12}$$

where $\bar{\alpha}_X$ is the population-level binding reliability
(estimated from TFs present in multiple binding datasets) and
$\bar{\alpha}_Y$ is the population-level perturbation reliability.

### 5.2 Two Binding, Two Perturbation Datasets

Using $X_1 =$ `callingcards`, $X_2 =$ `harbison` (YPD), $Y_1 =$ `kemmeren`,
$Y_2 =$ `hughes_knockout`:

$$\hat{\rho}_{\phi\psi}^{(k)} =
\frac{\left(r_{X_1 Y_1}^{(k)}\,r_{X_1 Y_2}^{(k)}\,r_{X_2 Y_1}^{(k)}\,r_{X_2 Y_2}^{(k)}\right)^{1/4}}{\sqrt{r_{X_1 X_2}^{(k)} \cdot r_{Y_1 Y_2}^{(k)}}}
\tag{13}$$

All four correlations are computed over the set of genes covered by both
datasets for TF $k$.

### 5.3 Full Multi-Dataset Version

With $N = 4$ binding datasets and $M = 3$ perturbation datasets, applying
Eq. 7 per TF:

$$\hat{\rho}_{\phi\psi}^{(k)} =
\frac{\displaystyle\left(\prod_{i=1}^{4}\prod_{j=1}^{3} r_{X_i^{(k)} Y_j^{(k)}}\right)^{1/12}}
{\sqrt{\displaystyle\hat{\alpha}_X^{(k)} \cdot \hat{\alpha}_Y^{(k)}}}
\tag{14}$$

where $\hat{\alpha}_X^{(k)}$ and $\hat{\alpha}_Y^{(k)}$ are from
Eqs. 9 and 11.

---

## 6. Population-Level (Pooled) Reliability

Per-TF reliability estimates are noisy when $G$ (gene coverage) is small or
when the TF has few measured targets above noise. The paper recommends
pooling across all TFs to obtain a global modality reliability that can then
be used in Eq. 12 for TFs lacking multi-dataset coverage.

$$\bar{\alpha}_X =
\left(\prod_{k \in \mathcal{K}_{XX}} r_{X_1^{(k)},\, X_2^{(k)}}\right)^{1/|\mathcal{K}_{XX}|}
\tag{15}$$

where $\mathcal{K}_{XX}$ is the set of TFs with data in both binding
datasets. $\bar{\alpha}_Y$ is defined analogously over $\mathcal{K}_{YY}$.

Concretely, this means computing the binding-binding pairwise correlation
for each of the 102 TFs shared between `callingcards` and `harbison` (or
whichever pair has the most coverage), then taking the geometric mean
across those 102 values.

---

## 7. Score Alignment and Comparability

Before computing any pairwise correlation, scores from different datasets
must be reduced to a common (target gene) basis for the same TF.

**Recommended score transformations:**

| Dataset | Raw column | Suggested transform |
|---|---|---|
| `callingcards` | `callingcards_enrichment` | $\log_2(\text{enrichment} + 1)$ or $-\log_{10}(\text{poisson\_pval})$ |
| `harbison` | `effect` | already log$_2$ ratio; restrict to YPD for cross-study coherence |
| `rossi` | `enrichment` | $\log_2(\text{enrichment} + 1)$ or $-\log_{10}(\text{poisson\_pval})$ |
| `chec_m2025` | `enrichment` | same as rossi |
| `kemmeren` | `M` | already log$_2$ FC |
| `hughes_knockout` | `mean_norm_log2fc` | already log$_2$ FC |
| `degron` | `log2FoldChange` | already log$_2$ FC; choose an appropriate timepoint |

A single row per (TF, gene) per dataset is required. For datasets that
contain multiple rows per pair (e.g. `rossi`, which has genomic-window
resolution), aggregate to gene-level by taking the maximum enrichment or
minimum p-value per target gene.

---

## 8. Asymmetry Note

Unlike mRNA vs. protein, binding and perturbation are not symmetric
modalities. A TF can have high binding enrichment at a target but produce
no detectable perturbation effect (buffered regulation, redundancy,
condition-specificity), and a target gene can show a strong perturbation
response through indirect effects not captured by the binding assay. This
means a low observed $r_{XY}$ does not necessarily imply low true
$\rho_{\phi\psi}$ -- it may instead reflect genuine biological complexity.
The Spearman correction addresses only the noise-induced component of
attenuation; condition-mismatch and indirect-effect biases remain.

In particular, `harbison` and `callingcards` are largely YPD experiments,
while `kemmeren`, `hughes_knockout`, and `degron` also use YPD or
near-YPD conditions, so condition alignment is reasonable. If future
analyses extend to stress conditions in `harbison` or condition-specific
`degron` timepoints, reliability estimates should be computed within
matched conditions.

---

## 9. Summary of Equations

| Equation | Purpose |
|---|---|
| Eq. 2 | Reliability: fraction of variance that is signal |
| Eq. 3 | Replicate correlation = geometric mean of reliabilities |
| Eq. 4 | Observed cross-modal correlation is attenuated by $\sqrt{\alpha_X \alpha_Y}$ |
| Eq. 6 | Spearman correction with 2 binding + 2 perturbation datasets |
| Eq. 7 | General correction with $N$ binding + $M$ perturbation datasets |
| Eq. 9 | Per-TF binding reliability (geometric mean of pairwise cross-dataset $r$) |
| Eq. 11 | Per-TF perturbation reliability (same, for perturbation datasets) |
| Eq. 13 | Per-TF corrected correlation (2+2 dataset case, concrete dataset names) |
| Eq. 14 | Per-TF corrected correlation (full 4+3 dataset case) |
| Eq. 15 | Population-level pooled reliability for imputation |
