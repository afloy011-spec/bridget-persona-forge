# QA report

Every frame that ships was measured. This file is the measurement, not a claim
about it. Thresholds live in `assets.json → gates`; the reasoning behind each
one is in the Russian `_` keys next to it and in the docstrings of
`scripts/metrics/`.

Three states, not two. A gate that could not be computed reports
**NOT_MEASURED**, and a required gate in that state blocks the frame from
shipping. A gate that silently switches itself off when a dependency is missing
produces a false pass, which is worse than no gate at all.

## Part 1 — profile set

70 of 70 generated frames pass the gates.
0 failed, 0 could not be measured.

**Set consistency of the DELIVERED frames** — the headline number for the
brief's first criterion, because the reviewer sees the delivered set and
nothing else. Worst pairwise ArcFace cosine: **0.711** on the pair `P3` × `P5`, mean 0.763 over 10 pairs of the 5 delivered frames.
The minimum is what matters: a healthy-looking mean hides the worst pair.
This number is reported, not enforced — see
`assets.json → gates._identity_is_informational` and its erratum.

*For comparison, across the whole pool that passed the gates (which is what
`gates.py` prints, and what it uses to decide which cell to re-shoot):*
worst pair **0.603** (`P2_s9105_01.png` × `P5_s1926130485_01.png`), mean 0.753, over 2415 pairs of 70 shipping frames.

**Does each gate actually separate anything?** A gate that has never once said
no is indistinguishable from a gate that does not work, and the per-frame table
below cannot show the difference. This one can.

| gate | role | PASS | FAIL | NOT_MEASURED | on this pool |
|---|---|---|---|---|---|
| `chroma` | required | 70 | 0 | 0 | **constant PASS on this pool** |
| `sharp` | required | 70 | 0 | 0 | **constant PASS on this pool** |
| `skin` | required | 70 | 0 | 0 | **constant PASS on this pool** |
| `identity` | informational | 1 | 69 | 0 | separates |
| `cohort` | informational | 69 | 1 | 0 | separates |
| `age` | informational | 15 | 55 | 0 | separates |
| `tattoo` | informational | 0 | 0 | 40 | **never produced a number** (40 not measured, n/a on the other 30) |
| `detector` | informational | 0 | 0 | 70 | **never produced a number** (70 not measured) |

The required gates are constant PASS here **on frames that shipped**, which is
what "these frames are clean" is supposed to look like — but it is only
evidence if the gate can fail at all. `scripts/gate_firing.py` proves it can:
it takes a frame the gates passed, degrades it with exactly the defect that
gate exists to catch, and records the step where the gate first says no
(`docs/<project>/gate_firing.md`). Chroma fires at 50% desaturation, sharpness
at a Gaussian σ of 1.0, skin at a bilateral radius of 15.

| frame | verdict | age | brows | chroma | cohort | detector | hair_roots | hair_tone | identity | iris | lips | sharp | skin | tattoo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `P1_s1206582321_01.png` | **PASS** | FAIL 41 | PASS 0.00507 | PASS 0.44 | PASS 0.769 | NOT_MEASURED | NOT_MEASURED | PASS 0.103 | FAIL 0.709 | PASS 119 | PASS 1.64 | PASS 183 | PASS 0 | — |
| `P1_s171403609_01.png` | **PASS** | PASS 51 | PASS 0.0108 | PASS 0.438 | PASS 0.76 | NOT_MEASURED | NOT_MEASURED | PASS 0.23 | FAIL 0.686 | PASS 107 | PASS 1.75 | PASS 165 | PASS 0 | — |
| `P1_s1907010619_01.png` | **PASS** | FAIL 42 | FAIL 0.00488 | PASS 0.439 | PASS 0.752 | NOT_MEASURED | PASS 0.454 | PASS 0.188 | FAIL 0.713 | PASS 123 | PASS 1.56 | PASS 157 | PASS 0 | — |
| `P1_s1926130485_01.png` | **PASS** | PASS 48 | PASS 0.00861 | PASS 0.451 | PASS 0.753 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | PASS 0.758 | PASS 103 | PASS 1.64 | PASS 148 | PASS 0 | — |
| `P1_s2141552288_01.png` | **PASS** | FAIL 44 | PASS 0.0187 | PASS 0.427 | PASS 0.75 | NOT_MEASURED | FAIL 0.00571 | PASS 0.111 | FAIL 0.704 | PASS 112 | PASS 1.64 | PASS 145 | PASS 0 | — |
| `P1_s258197991_01.png` | **PASS** | PASS 49 | PASS 0.0123 | PASS 0.437 | PASS 0.724 | NOT_MEASURED | PASS 0.0335 | PASS 0.15 | FAIL 0.709 | PASS 112 | PASS 1.7 | PASS 153 | PASS 0 | — |
| `P1_s308585876_01.png` | **PASS** | FAIL 41 | PASS 0.0168 | PASS 0.43 | PASS 0.777 | NOT_MEASURED | PASS 0.17 | PASS 0.173 | FAIL 0.67 | PASS 112 | PASS 1.63 | PASS 157 | PASS 0 | — |
| `P1_s41671491_01.png` | **PASS** | FAIL 38 | PASS 0.0067 | PASS 0.445 | PASS 0.735 | NOT_MEASURED | PASS 0.5 | PASS 0.204 | FAIL 0.688 | PASS 108 | PASS 1.66 | PASS 143 | PASS 0 | — |
| `P2_s1206582321_01.png` | **PASS** | FAIL 42 | PASS 0.00587 | PASS 0.459 | PASS 0.767 | NOT_MEASURED | PASS 0.815 | PASS 0.173 | FAIL 0.644 | NOT_MEASURED | PASS 1.49 | PASS 192 | PASS 0 | — |
| `P2_s171403609_01.png` | **PASS** | FAIL 35 | NOT_MEASURED | PASS 0.485 | PASS 0.762 | NOT_MEASURED | PASS 0.73 | PASS 0.413 | FAIL 0.656 | PASS 123 | PASS 1.51 | PASS 165 | PASS 0 | — |
| `P2_s1907010619_01.png` | **PASS** | FAIL 38 | PASS 0.0249 | PASS 0.47 | PASS 0.744 | NOT_MEASURED | PASS 0.418 | PASS 0.122 | FAIL 0.667 | PASS 129 | PASS 1.36 | PASS 216 | PASS 0 | — |
| `P2_s1926130485_01.png` | **PASS** | FAIL 38 | NOT_MEASURED | PASS 0.48 | PASS 0.759 | NOT_MEASURED | PASS 0.77 | PASS 0.104 | FAIL 0.656 | NOT_MEASURED | PASS 1.4 | PASS 122 | PASS 0 | — |
| `P2_s2141552288_01.png` | **PASS** | FAIL 33 | NOT_MEASURED | PASS 0.481 | PASS 0.733 | NOT_MEASURED | PASS 0.854 | PASS 0.107 | FAIL 0.631 | NOT_MEASURED | PASS 1.36 | PASS 256 | PASS 0 | — |
| `P2_s258197991_01.png` | **PASS** | FAIL 37 | FAIL 0.00138 | PASS 0.441 | PASS 0.731 | NOT_MEASURED | PASS 0.856 | FAIL 0.0834 | FAIL 0.66 | PASS 128 | NOT_MEASURED | PASS 130 | PASS 0 | — |
| `P2_s308585876_01.png` | **PASS** | PASS 46 | PASS 0.0151 | PASS 0.472 | PASS 0.775 | NOT_MEASURED | PASS 1.09 | PASS 0.153 | FAIL 0.64 | NOT_MEASURED | PASS 1.51 | PASS 185 | PASS 0 | — |
| `P2_s41671491_01.png` | **PASS** | FAIL 35 | PASS 0.0229 | PASS 0.461 | PASS 0.75 | NOT_MEASURED | NOT_MEASURED | PASS 0.206 | FAIL 0.644 | NOT_MEASURED | PASS 1.41 | PASS 165 | PASS 0 | — |
| `P2_s9101_01.png` | **PASS** | PASS 51 | PASS 0.00657 | PASS 0.444 | FAIL 0.712 | NOT_MEASURED | PASS 1.04 | PASS 0.136 | FAIL 0.611 | NOT_MEASURED | PASS 1.4 | PASS 256 | PASS 0 | — |
| `P2_s9102_01.png` | **PASS** | FAIL 36 | NOT_MEASURED | PASS 0.472 | PASS 0.722 | NOT_MEASURED | NOT_MEASURED | PASS 0.221 | FAIL 0.659 | NOT_MEASURED | PASS 1.49 | PASS 165 | PASS 0 | — |
| `P2_s9103_01.png` | **PASS** | PASS 45 | PASS 0.0118 | PASS 0.491 | PASS 0.768 | NOT_MEASURED | PASS 0.923 | PASS 0.162 | FAIL 0.663 | PASS 142 | PASS 1.32 | PASS 317 | PASS 0 | — |
| `P2_s9104_01.png` | **PASS** | PASS 46 | PASS 0.00942 | PASS 0.448 | PASS 0.759 | NOT_MEASURED | PASS 0.911 | PASS 0.11 | FAIL 0.652 | PASS 128 | PASS 1.36 | PASS 192 | PASS 0 | — |
| `P2_s9105_01.png` | **PASS** | FAIL 40 | PASS 0.0144 | PASS 0.46 | PASS 0.722 | NOT_MEASURED | NOT_MEASURED | FAIL 0.0686 | FAIL 0.596 | PASS 135 | PASS 1.42 | PASS 163 | PASS 0 | — |
| `P2_s9106_01.png` | **PASS** | FAIL 43 | FAIL -3.73e-05 | PASS 0.449 | PASS 0.748 | NOT_MEASURED | PASS 1.07 | FAIL 0.0899 | FAIL 0.603 | PASS 124 | PASS 1.27 | PASS 173 | PASS 0.000295 | — |
| `P3_s1206582321_01.png` | **PASS** | FAIL 41 | NOT_MEASURED | PASS 0.641 | PASS 0.753 | NOT_MEASURED | PASS 0.153 | PASS 0.204 | FAIL 0.617 | PASS 117 | PASS 1.49 | PASS 392 | PASS 0 | NOT_MEASURED |
| `P3_s171403609_01.png` | **PASS** | PASS 45 | NOT_MEASURED | PASS 0.625 | PASS 0.765 | NOT_MEASURED | PASS 0.232 | PASS 0.142 | FAIL 0.598 | PASS 115 | PASS 1.5 | PASS 422 | PASS 0 | NOT_MEASURED |
| `P3_s1907010619_01.png` | **PASS** | FAIL 43 | PASS 0.0124 | PASS 0.672 | PASS 0.749 | NOT_MEASURED | PASS 0.245 | PASS 0.146 | FAIL 0.631 | PASS 121 | NOT_MEASURED | PASS 234 | PASS 0 | NOT_MEASURED |
| `P3_s1926130485_01.png` | **PASS** | FAIL 41 | PASS 0.0124 | PASS 0.665 | PASS 0.761 | NOT_MEASURED | FAIL -0.0608 | PASS 0.183 | FAIL 0.659 | PASS 117 | PASS 1.51 | PASS 179 | PASS 0 | NOT_MEASURED |
| `P3_s2141552288_01.png` | **PASS** | PASS 47 | PASS 0.0166 | PASS 0.651 | PASS 0.729 | NOT_MEASURED | PASS 0.11 | PASS 0.153 | FAIL 0.649 | PASS 122 | PASS 1.55 | PASS 202 | PASS 0 | NOT_MEASURED |
| `P3_s258197991_01.png` | **PASS** | FAIL 39 | NOT_MEASURED | PASS 0.633 | PASS 0.777 | NOT_MEASURED | PASS 0.0918 | PASS 0.178 | FAIL 0.656 | PASS 106 | PASS 1.62 | PASS 216 | PASS 0 | NOT_MEASURED |
| `P3_s308585876_01.png` | **PASS** | FAIL 41 | NOT_MEASURED | PASS 0.653 | PASS 0.776 | NOT_MEASURED | FAIL -0.182 | PASS 0.217 | FAIL 0.717 | PASS 123 | PASS 1.51 | PASS 136 | PASS 0 | NOT_MEASURED |
| `P3_s41671491_01.png` | **PASS** | FAIL 39 | PASS 0.0231 | PASS 0.648 | PASS 0.78 | NOT_MEASURED | PASS 0.0133 | PASS 0.132 | FAIL 0.653 | PASS 117 | PASS 1.7 | PASS 200 | PASS 0 | NOT_MEASURED |
| `P3_s9101_01.png` | **PASS** | FAIL 44 | NOT_MEASURED | PASS 0.666 | PASS 0.773 | NOT_MEASURED | PASS 0.143 | PASS 0.161 | FAIL 0.647 | PASS 120 | PASS 1.58 | PASS 340 | PASS 0 | NOT_MEASURED |
| `P3_s9102_01.png` | **PASS** | FAIL 40 | PASS 0.0142 | PASS 0.67 | PASS 0.784 | NOT_MEASURED | PASS 0.396 | PASS 0.141 | FAIL 0.648 | PASS 106 | PASS 1.49 | PASS 331 | PASS 0 | NOT_MEASURED |
| `P3_s9103_01.png` | **PASS** | FAIL 44 | NOT_MEASURED | PASS 0.678 | PASS 0.753 | NOT_MEASURED | FAIL -0.088 | PASS 0.181 | FAIL 0.647 | PASS 119 | PASS 1.48 | PASS 318 | PASS 0 | NOT_MEASURED |
| `P3_s9104_01.png` | **PASS** | PASS 48 | PASS 0.0206 | PASS 0.657 | PASS 0.785 | NOT_MEASURED | FAIL -0.0405 | PASS 0.248 | FAIL 0.647 | PASS 112 | PASS 1.58 | PASS 220 | PASS 0 | NOT_MEASURED |
| `P3_s9105_01.png` | **PASS** | FAIL 38 | NOT_MEASURED | PASS 0.669 | PASS 0.776 | NOT_MEASURED | PASS 0.309 | PASS 0.136 | FAIL 0.646 | PASS 132 | PASS 1.49 | PASS 369 | PASS 0 | NOT_MEASURED |
| `P3_s9106_01.png` | **PASS** | FAIL 41 | NOT_MEASURED | PASS 0.661 | PASS 0.731 | NOT_MEASURED | PASS 0.178 | PASS 0.161 | FAIL 0.575 | PASS 124 | PASS 1.59 | PASS 419 | PASS 0 | NOT_MEASURED |
| `P3_s9201_01.png` | **PASS** | PASS 47 | PASS 0.0146 | PASS 0.658 | PASS 0.762 | NOT_MEASURED | FAIL -0.026 | PASS 0.251 | FAIL 0.656 | PASS 108 | PASS 1.61 | PASS 187 | PASS 0 | NOT_MEASURED |
| `P3_s9202_01.png` | **PASS** | PASS 46 | NOT_MEASURED | PASS 0.663 | PASS 0.758 | NOT_MEASURED | PASS 0.099 | PASS 0.16 | FAIL 0.613 | PASS 111 | PASS 1.6 | PASS 325 | PASS 0 | NOT_MEASURED |
| `P3_s9203_01.png` | **PASS** | FAIL 44 | NOT_MEASURED | PASS 0.663 | PASS 0.764 | NOT_MEASURED | PASS 0.217 | FAIL 0.0911 | FAIL 0.636 | PASS 115 | PASS 1.54 | PASS 204 | PASS 0 | NOT_MEASURED |
| `P3_s9204_01.png` | **PASS** | FAIL 42 | PASS 0.0127 | PASS 0.673 | PASS 0.756 | NOT_MEASURED | PASS 0.222 | PASS 0.179 | FAIL 0.635 | PASS 119 | PASS 1.5 | PASS 258 | PASS 0 | NOT_MEASURED |
| `P3_s9205_01.png` | **PASS** | PASS 49 | FAIL -0.00697 | PASS 0.663 | PASS 0.753 | NOT_MEASURED | FAIL -0.0967 | PASS 0.215 | FAIL 0.646 | PASS 124 | PASS 1.5 | PASS 210 | PASS 0 | NOT_MEASURED |
| `P3_s9206_01.png` | **PASS** | FAIL 39 | PASS 0.0149 | PASS 0.654 | PASS 0.753 | NOT_MEASURED | PASS 0.287 | PASS 0.159 | FAIL 0.617 | PASS 128 | PASS 1.36 | PASS 248 | PASS 0 | NOT_MEASURED |
| `P4_s1206582321_01.png` | **PASS** | FAIL 39 | PASS 0.0172 | PASS 0.505 | PASS 0.746 | NOT_MEASURED | PASS 0.181 | PASS 0.333 | FAIL 0.649 | PASS 108 | PASS 1.94 | PASS 171 | PASS 0 | — |
| `P4_s171403609_01.png` | **PASS** | FAIL 38 | PASS 0.0117 | PASS 0.527 | PASS 0.757 | NOT_MEASURED | NOT_MEASURED | PASS 0.349 | FAIL 0.64 | PASS 120 | PASS 2.28 | PASS 132 | PASS 0 | — |
| `P4_s1907010619_01.png` | **PASS** | PASS 49 | PASS 0.0121 | PASS 0.543 | PASS 0.774 | NOT_MEASURED | FAIL -0.0232 | PASS 0.256 | FAIL 0.679 | PASS 110 | PASS 1.85 | PASS 119 | PASS 0 | — |
| `P4_s1926130485_01.png` | **PASS** | PASS 47 | PASS 0.0174 | PASS 0.485 | PASS 0.754 | NOT_MEASURED | FAIL -0.0423 | PASS 0.147 | FAIL 0.666 | PASS 126 | PASS 1.88 | PASS 122 | PASS 0 | — |
| `P4_s2141552288_01.png` | **PASS** | FAIL 44 | PASS 0.0153 | PASS 0.547 | PASS 0.751 | NOT_MEASURED | FAIL -0.0751 | PASS 0.144 | FAIL 0.67 | PASS 111 | PASS 2 | PASS 136 | PASS 0 | — |
| `P4_s258197991_01.png` | **PASS** | FAIL 31 | NOT_MEASURED | PASS 0.481 | PASS 0.739 | NOT_MEASURED | PASS 0.111 | PASS 0.267 | FAIL 0.618 | PASS 104 | PASS 2.15 | PASS 197 | PASS 0 | — |
| `P4_s308585876_01.png` | **PASS** | FAIL 41 | PASS 0.0288 | PASS 0.516 | PASS 0.765 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.639 | PASS 114 | PASS 1.94 | PASS 118 | PASS 0 | — |
| `P4_s41671491_01.png` | **PASS** | FAIL 38 | NOT_MEASURED | PASS 0.504 | PASS 0.736 | NOT_MEASURED | PASS 0.0671 | PASS 0.391 | FAIL 0.653 | PASS 107 | PASS 2 | PASS 135 | PASS 0 | — |
| `P5_s1206582321_01.png` | **PASS** | FAIL 39 | NOT_MEASURED | PASS 0.485 | PASS 0.749 | NOT_MEASURED | NOT_MEASURED | PASS 0.167 | FAIL 0.659 | PASS 121 | NOT_MEASURED | PASS 192 | PASS 0 | NOT_MEASURED |
| `P5_s171403609_01.png` | **PASS** | FAIL 32 | NOT_MEASURED | PASS 0.494 | PASS 0.751 | NOT_MEASURED | PASS 0.574 | PASS 0.136 | FAIL 0.678 | NOT_MEASURED | NOT_MEASURED | PASS 244 | PASS 0 | NOT_MEASURED |
| `P5_s1907010619_01.png` | **PASS** | FAIL 36 | PASS 0.0191 | PASS 0.501 | PASS 0.756 | NOT_MEASURED | PASS 0.498 | PASS 0.109 | FAIL 0.603 | PASS 128 | NOT_MEASURED | PASS 226 | PASS 0 | NOT_MEASURED |
| `P5_s1926130485_01.png` | **PASS** | FAIL 31 | NOT_MEASURED | PASS 0.475 | PASS 0.738 | NOT_MEASURED | NOT_MEASURED | PASS 0.117 | FAIL 0.61 | PASS 118 | NOT_MEASURED | PASS 211 | PASS 0 | NOT_MEASURED |
| `P5_s2141552288_01.png` | **PASS** | FAIL 38 | PASS 0.0275 | PASS 0.527 | PASS 0.77 | NOT_MEASURED | PASS 0.639 | PASS 0.112 | FAIL 0.657 | PASS 131 | NOT_MEASURED | PASS 235 | PASS 0 | NOT_MEASURED |
| `P5_s258197991_01.png` | **PASS** | FAIL 35 | PASS 0.0226 | PASS 0.488 | PASS 0.761 | NOT_MEASURED | NOT_MEASURED | PASS 0.173 | FAIL 0.61 | PASS 121 | NOT_MEASURED | PASS 199 | PASS 0 | NOT_MEASURED |
| `P5_s308585876_01.png` | **PASS** | FAIL 38 | PASS 0.0154 | PASS 0.492 | PASS 0.749 | NOT_MEASURED | NOT_MEASURED | PASS 0.161 | FAIL 0.58 | PASS 106 | NOT_MEASURED | PASS 171 | PASS 0 | NOT_MEASURED |
| `P5_s41671491_01.png` | **PASS** | FAIL 33 | NOT_MEASURED | PASS 0.494 | PASS 0.731 | NOT_MEASURED | PASS 0.549 | PASS 0.153 | FAIL 0.598 | PASS 111 | NOT_MEASURED | PASS 229 | PASS 0 | NOT_MEASURED |
| `P5_s9101_01.png` | **PASS** | FAIL 37 | NOT_MEASURED | PASS 0.527 | PASS 0.752 | NOT_MEASURED | NOT_MEASURED | PASS 0.161 | FAIL 0.694 | PASS 111 | NOT_MEASURED | PASS 208 | PASS 0 | NOT_MEASURED |
| `P5_s9102_01.png` | **PASS** | FAIL 32 | NOT_MEASURED | PASS 0.519 | PASS 0.745 | NOT_MEASURED | PASS 0.407 | PASS 0.129 | FAIL 0.586 | PASS 126 | NOT_MEASURED | PASS 198 | PASS 0 | NOT_MEASURED |
| `P5_s9103_01.png` | **PASS** | FAIL 33 | NOT_MEASURED | PASS 0.543 | PASS 0.775 | NOT_MEASURED | PASS 0.491 | PASS 0.147 | FAIL 0.659 | PASS 123 | NOT_MEASURED | PASS 238 | PASS 0 | NOT_MEASURED |
| `P5_s9104_01.png` | **PASS** | FAIL 32 | NOT_MEASURED | PASS 0.583 | PASS 0.752 | NOT_MEASURED | NOT_MEASURED | PASS 0.109 | FAIL 0.563 | PASS 128 | NOT_MEASURED | PASS 222 | PASS 0 | NOT_MEASURED |
| `P5_s9105_01.png` | **PASS** | FAIL 40 | PASS 0.0186 | PASS 0.559 | PASS 0.765 | NOT_MEASURED | NOT_MEASURED | PASS 0.117 | FAIL 0.666 | PASS 124 | NOT_MEASURED | PASS 212 | PASS 0 | NOT_MEASURED |
| `P5_s9106_01.png` | **PASS** | FAIL 33 | NOT_MEASURED | PASS 0.583 | PASS 0.754 | NOT_MEASURED | NOT_MEASURED | PASS 0.107 | FAIL 0.585 | PASS 115 | NOT_MEASURED | PASS 210 | PASS 0 | NOT_MEASURED |
| `P5_s9201_01.png` | **PASS** | FAIL 33 | NOT_MEASURED | PASS 0.556 | PASS 0.746 | NOT_MEASURED | NOT_MEASURED | PASS 0.0992 | FAIL 0.633 | PASS 125 | NOT_MEASURED | PASS 230 | PASS 0 | NOT_MEASURED |
| `P5_s9202_01.png` | **PASS** | FAIL 34 | NOT_MEASURED | PASS 0.573 | PASS 0.744 | NOT_MEASURED | NOT_MEASURED | PASS 0.125 | FAIL 0.628 | PASS 126 | NOT_MEASURED | PASS 218 | PASS 0 | NOT_MEASURED |
| `P5_s9203_01.png` | **PASS** | FAIL 30 | NOT_MEASURED | PASS 0.584 | PASS 0.745 | NOT_MEASURED | PASS 0.648 | PASS 0.134 | FAIL 0.656 | NOT_MEASURED | NOT_MEASURED | PASS 242 | PASS 0 | NOT_MEASURED |
| `P5_s9204_01.png` | **PASS** | FAIL 31 | NOT_MEASURED | PASS 0.605 | PASS 0.723 | NOT_MEASURED | NOT_MEASURED | PASS 0.127 | FAIL 0.648 | PASS 124 | NOT_MEASURED | PASS 272 | PASS 0 | NOT_MEASURED |
| `P5_s9205_01.png` | **PASS** | FAIL 34 | NOT_MEASURED | PASS 0.608 | PASS 0.742 | NOT_MEASURED | PASS 0.718 | PASS 0.124 | FAIL 0.599 | PASS 119 | NOT_MEASURED | PASS 271 | PASS 0 | NOT_MEASURED |
| `P5_s9206_01.png` | **PASS** | FAIL 39 | PASS 0.0215 | PASS 0.539 | PASS 0.767 | NOT_MEASURED | PASS 0.56 | PASS 0.128 | FAIL 0.657 | PASS 121 | NOT_MEASURED | PASS 196 | PASS 0 | NOT_MEASURED |

## Part 2 — photo story

40 of 40 generated frames pass the gates.
0 failed, 0 could not be measured.

**Set consistency of the DELIVERED frames** — the headline number for the
brief's first criterion, because the reviewer sees the delivered set and
nothing else. Worst pairwise ArcFace cosine: **0.726** on the pair `S2` × `S4`, mean 0.767 over 10 pairs of the 5 delivered frames.
The minimum is what matters: a healthy-looking mean hides the worst pair.
This number is reported, not enforced — see
`assets.json → gates._identity_is_informational` and its erratum.

*For comparison, across the whole pool that passed the gates (which is what
`gates.py` prints, and what it uses to decide which cell to re-shoot):*
worst pair **0.542** (`S3_s250345807_01.png` × `S4_s630550919_01.png`), mean 0.751, over 780 pairs of 40 shipping frames.

**Does each gate actually separate anything?** A gate that has never once said
no is indistinguishable from a gate that does not work, and the per-frame table
below cannot show the difference. This one can.

| gate | role | PASS | FAIL | NOT_MEASURED | on this pool |
|---|---|---|---|---|---|
| `chroma` | required | 40 | 0 | 0 | **constant PASS on this pool** |
| `sharp` | required | 40 | 0 | 0 | **constant PASS on this pool** |
| `skin` | required | 40 | 0 | 0 | **constant PASS on this pool** |
| `identity` | informational | 1 | 39 | 0 | separates |
| `cohort` | informational | 37 | 3 | 0 | separates |
| `age` | informational | 16 | 24 | 0 | separates |
| `tattoo` | informational | 0 | 0 | 8 | **never produced a number** (8 not measured, n/a on the other 32) |
| `detector` | informational | 0 | 0 | 40 | **never produced a number** (40 not measured) |

The required gates are constant PASS here **on frames that shipped**, which is
what "these frames are clean" is supposed to look like — but it is only
evidence if the gate can fail at all. `scripts/gate_firing.py` proves it can:
it takes a frame the gates passed, degrades it with exactly the defect that
gate exists to catch, and records the step where the gate first says no
(`docs/<project>/gate_firing.md`). Chroma fires at 50% desaturation, sharpness
at a Gaussian σ of 1.0, skin at a bilateral radius of 15.

| frame | verdict | age | brows | chroma | cohort | detector | hair_roots | hair_tone | identity | iris | lips | sharp | skin | tattoo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `S1_s1215653706_01.png` | **PASS** | PASS 46 | NOT_MEASURED | PASS 0.42 | PASS 0.76 | NOT_MEASURED | FAIL -0.0896 | PASS 0.2 | FAIL 0.663 | PASS 115 | PASS 1.65 | PASS 278 | PASS 0 | — |
| `S1_s1492719930_01.png` | **PASS** | PASS 48 | PASS 0.0171 | PASS 0.454 | PASS 0.776 | NOT_MEASURED | FAIL -0.00546 | PASS 0.268 | FAIL 0.661 | PASS 117 | PASS 1.78 | PASS 304 | PASS 0 | — |
| `S1_s1702179205_01.png` | **PASS** | FAIL 37 | PASS 0.0245 | PASS 0.452 | PASS 0.77 | NOT_MEASURED | FAIL -0.162 | PASS 0.206 | FAIL 0.681 | PASS 120 | PASS 1.91 | PASS 394 | PASS 0 | — |
| `S1_s1870241204_01.png` | **PASS** | FAIL 40 | FAIL 0.000147 | PASS 0.454 | PASS 0.773 | NOT_MEASURED | PASS 0.0226 | PASS 0.207 | FAIL 0.686 | PASS 121 | PASS 1.69 | PASS 366 | PASS 0 | — |
| `S1_s250345807_01.png` | **PASS** | FAIL 44 | NOT_MEASURED | PASS 0.451 | PASS 0.765 | NOT_MEASURED | FAIL -0.00536 | PASS 0.469 | FAIL 0.663 | PASS 109 | PASS 1.76 | PASS 375 | PASS 0 | — |
| `S1_s630550919_01.png` | **PASS** | FAIL 39 | PASS 0.00714 | PASS 0.446 | PASS 0.78 | NOT_MEASURED | FAIL -0.0623 | PASS 0.199 | FAIL 0.664 | PASS 128 | PASS 1.91 | PASS 362 | PASS 0 | — |
| `S1_s780113663_01.png` | **PASS** | FAIL 39 | PASS 0.0211 | PASS 0.467 | PASS 0.761 | NOT_MEASURED | FAIL -0.0272 | PASS 0.342 | FAIL 0.66 | PASS 130 | PASS 1.97 | PASS 341 | PASS 0 | — |
| `S1_s820586579_01.png` | **PASS** | PASS 50 | NOT_MEASURED | PASS 0.459 | PASS 0.779 | NOT_MEASURED | FAIL -0.0177 | PASS 0.195 | FAIL 0.671 | PASS 108 | PASS 1.76 | PASS 381 | PASS 0 | — |
| `S2_s1215653706_01.png` | **PASS** | FAIL 38 | FAIL 0.0046 | PASS 0.484 | PASS 0.727 | NOT_MEASURED | NOT_MEASURED | PASS 0.246 | FAIL 0.655 | PASS 124 | PASS 1.7 | PASS 233 | PASS 0 | NOT_MEASURED |
| `S2_s1492719930_01.png` | **PASS** | PASS 46 | PASS 0.0288 | PASS 0.47 | PASS 0.779 | NOT_MEASURED | PASS 0.397 | FAIL 0.0437 | FAIL 0.666 | PASS 126 | PASS 1.74 | PASS 215 | PASS 0 | NOT_MEASURED |
| `S2_s1702179205_01.png` | **PASS** | PASS 52 | PASS 0.0188 | PASS 0.467 | PASS 0.764 | NOT_MEASURED | NOT_MEASURED | PASS 0.114 | FAIL 0.655 | PASS 121 | PASS 1.8 | PASS 244 | PASS 0 | NOT_MEASURED |
| `S2_s1870241204_01.png` | **PASS** | FAIL 36 | PASS 0.0207 | PASS 0.47 | PASS 0.775 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.652 | PASS 121 | PASS 1.85 | PASS 243 | PASS 0 | NOT_MEASURED |
| `S2_s250345807_01.png` | **PASS** | PASS 47 | PASS 0.0226 | PASS 0.44 | FAIL 0.707 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.649 | PASS 95.8 | PASS 1.72 | PASS 216 | PASS 0.00018 | NOT_MEASURED |
| `S2_s630550919_01.png` | **PASS** | FAIL 35 | PASS 0.016 | PASS 0.482 | PASS 0.743 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.675 | PASS 135 | PASS 1.67 | PASS 273 | PASS 0 | NOT_MEASURED |
| `S2_s780113663_01.png` | **PASS** | FAIL 35 | NOT_MEASURED | PASS 0.486 | PASS 0.752 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.663 | PASS 123 | PASS 1.62 | PASS 277 | PASS 0 | NOT_MEASURED |
| `S2_s820586579_01.png` | **PASS** | FAIL 41 | PASS 0.0245 | PASS 0.47 | PASS 0.738 | NOT_MEASURED | NOT_MEASURED | PASS 0.123 | FAIL 0.651 | NOT_MEASURED | PASS 1.55 | PASS 249 | PASS 0.000357 | NOT_MEASURED |
| `S3_s1215653706_01.png` | **PASS** | FAIL 39 | FAIL 0.00123 | PASS 0.442 | PASS 0.737 | NOT_MEASURED | NOT_MEASURED | PASS 0.133 | FAIL 0.616 | PASS 114 | NOT_MEASURED | PASS 270 | PASS 0 | — |
| `S3_s1492719930_01.png` | **PASS** | FAIL 35 | PASS 0.0177 | PASS 0.384 | PASS 0.739 | NOT_MEASURED | PASS 0.179 | PASS 0.13 | FAIL 0.686 | PASS 123 | PASS 1.74 | PASS 301 | PASS 0 | — |
| `S3_s1702179205_01.png` | **PASS** | FAIL 39 | PASS 0.00999 | PASS 0.398 | PASS 0.746 | NOT_MEASURED | PASS 0.0778 | PASS 0.137 | FAIL 0.585 | PASS 126 | PASS 1.8 | PASS 241 | PASS 0 | — |
| `S3_s1870241204_01.png` | **PASS** | FAIL 41 | PASS 0.00729 | PASS 0.422 | PASS 0.754 | NOT_MEASURED | NOT_MEASURED | PASS 0.151 | FAIL 0.633 | PASS 110 | PASS 1.8 | PASS 297 | PASS 0 | — |
| `S3_s250345807_01.png` | **PASS** | FAIL 35 | PASS 0.0203 | PASS 0.414 | FAIL 0.716 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | FAIL 0.573 | PASS 135 | PASS 1.97 | PASS 273 | PASS 0 | — |
| `S3_s630550919_01.png` | **PASS** | FAIL 37 | NOT_MEASURED | PASS 0.436 | PASS 0.732 | NOT_MEASURED | NOT_MEASURED | PASS 0.118 | FAIL 0.592 | PASS 116 | NOT_MEASURED | PASS 238 | PASS 0 | — |
| `S3_s780113663_01.png` | **PASS** | FAIL 40 | NOT_MEASURED | PASS 0.42 | PASS 0.745 | NOT_MEASURED | NOT_MEASURED | PASS 0.132 | FAIL 0.655 | PASS 113 | PASS 1.91 | PASS 271 | PASS 0 | — |
| `S3_s820586579_01.png` | **PASS** | FAIL 35 | NOT_MEASURED | PASS 0.414 | PASS 0.738 | NOT_MEASURED | NOT_MEASURED | PASS 0.206 | FAIL 0.621 | PASS 130 | PASS 2.25 | PASS 290 | PASS 0 | — |
| `S4_s1215653706_01.png` | **PASS** | FAIL 42 | NOT_MEASURED | PASS 0.499 | PASS 0.75 | NOT_MEASURED | PASS 0.648 | PASS 0.121 | FAIL 0.669 | PASS 100 | PASS 1.7 | PASS 250 | PASS 0 | — |
| `S4_s1492719930_01.png` | **PASS** | PASS 49 | NOT_MEASURED | PASS 0.507 | PASS 0.725 | NOT_MEASURED | FAIL -0.0579 | PASS 0.295 | FAIL 0.669 | PASS 92.8 | PASS 1.72 | PASS 207 | PASS 0 | — |
| `S4_s1702179205_01.png` | **PASS** | PASS 51 | NOT_MEASURED | PASS 0.524 | PASS 0.751 | NOT_MEASURED | PASS 0.461 | PASS 0.327 | FAIL 0.644 | PASS 105 | PASS 1.68 | PASS 234 | PASS 0 | — |
| `S4_s1870241204_01.png` | **PASS** | PASS 54 | NOT_MEASURED | PASS 0.484 | PASS 0.769 | NOT_MEASURED | PASS 0.476 | PASS 0.153 | FAIL 0.7 | PASS 95.6 | NOT_MEASURED | PASS 240 | PASS 0 | — |
| `S4_s250345807_01.png` | **PASS** | PASS 47 | NOT_MEASURED | PASS 0.511 | PASS 0.745 | NOT_MEASURED | PASS 0.659 | PASS 0.162 | FAIL 0.622 | PASS 98 | PASS 1.67 | PASS 201 | PASS 0 | — |
| `S4_s630550919_01.png` | **PASS** | FAIL 41 | NOT_MEASURED | PASS 0.542 | FAIL 0.636 | NOT_MEASURED | FAIL -0.135 | PASS 0.123 | FAIL 0.594 | NOT_MEASURED | PASS 1.44 | PASS 193 | PASS 0.000326 | — |
| `S4_s780113663_01.png` | **PASS** | PASS 49 | NOT_MEASURED | PASS 0.525 | PASS 0.754 | NOT_MEASURED | PASS 0.216 | PASS 0.423 | FAIL 0.643 | PASS 91.7 | PASS 1.56 | PASS 175 | PASS 0 | — |
| `S4_s820586579_01.png` | **PASS** | PASS 46 | NOT_MEASURED | PASS 0.503 | PASS 0.752 | NOT_MEASURED | FAIL -0.0587 | PASS 0.389 | FAIL 0.611 | PASS 101 | PASS 1.63 | PASS 273 | PASS 0 | — |
| `S5_s1215653706_01.png` | **PASS** | PASS 47 | NOT_MEASURED | PASS 0.458 | PASS 0.752 | NOT_MEASURED | PASS 0.688 | FAIL 0.0632 | FAIL 0.597 | PASS 110 | PASS 1.74 | PASS 230 | PASS 0 | — |
| `S5_s1492719930_01.png` | **PASS** | PASS 47 | PASS 0.0341 | PASS 0.443 | PASS 0.757 | NOT_MEASURED | NOT_MEASURED | PASS 0.234 | FAIL 0.654 | PASS 117 | PASS 1.69 | PASS 220 | PASS 0 | — |
| `S5_s1702179205_01.png` | **PASS** | PASS 52 | PASS 0.02 | PASS 0.444 | PASS 0.78 | NOT_MEASURED | PASS 0.603 | PASS 0.109 | FAIL 0.7 | PASS 111 | PASS 1.68 | PASS 227 | PASS 0 | — |
| `S5_s1870241204_01.png` | **PASS** | FAIL 61 | PASS 0.0147 | PASS 0.436 | PASS 0.795 | NOT_MEASURED | PASS 0.522 | PASS 0.158 | PASS 0.722 | PASS 109 | PASS 1.57 | PASS 212 | PASS 0 | — |
| `S5_s250345807_01.png` | **PASS** | FAIL 43 | NOT_MEASURED | PASS 0.427 | PASS 0.749 | NOT_MEASURED | NOT_MEASURED | FAIL 0.0913 | FAIL 0.682 | PASS 106 | PASS 1.69 | PASS 268 | PASS 0 | — |
| `S5_s630550919_01.png` | **PASS** | FAIL 41 | NOT_MEASURED | PASS 0.446 | PASS 0.735 | NOT_MEASURED | NOT_MEASURED | PASS 0.13 | FAIL 0.651 | PASS 107 | PASS 1.68 | PASS 287 | PASS 0 | — |
| `S5_s780113663_01.png` | **PASS** | FAIL 42 | NOT_MEASURED | PASS 0.456 | PASS 0.755 | NOT_MEASURED | PASS 0.814 | PASS 0.116 | FAIL 0.6 | PASS 103 | PASS 1.68 | PASS 194 | PASS 0 | — |
| `S5_s820586579_01.png` | **PASS** | PASS 55 | NOT_MEASURED | PASS 0.457 | PASS 0.782 | NOT_MEASURED | PASS 0.0396 | PASS 0.199 | FAIL 0.692 | PASS 111 | PASS 1.68 | PASS 234 | PASS 0 | — |

## On "must pass an AI detector"

The brief asks that the images pass an AI detector as non-generated. This
pipeline answers that requirement **in the pixels** — by removing the things
that actually give generated images away: waxy skin with no pores, a face
sharper or softer than everything around it, a face that drifts between
frames, uniformly perfect focus, and the flat even light that no real room has.
Those are what the gates below measure.

It does **not** answer it in the metadata. An earlier version of
`scripts/lastmile.py` assembled a plausible capture story in EXIF — ISO, a
shutter speed derived from the exposure equation, focal length, aperture, flash
mode — and relied on the JPEG re-encode quietly dropping the ComfyUI graph
stored in the source PNG. That was removed deliberately. Forging capture
metadata and stripping the provenance of a photorealistic image of a person is
not craft, and it is not something this project does.

What is written instead, in three EXIF fields so that different viewers all
show it:

> AI-generated image of a fictional character. Not a photograph of a real person.

No external detector service is called by the pipeline, and no detector score
is reported here, because none was obtained. Anyone who wants one should run
the delivered files through a service of their choice.

## Thresholds in force

| gate | value |
|---|---|
| `age_above` | 7 |
| `age_below` | 6 |
| `brow_asymmetry_min` | 0.005 |
| `brow_higher_side` | left |
| `brow_max_yaw` | 0.15 |
| `brow_noise_max` | 0.03 |
| `colourfulness_min` | 18.0 |
| `face_sharp_canon_ipd` | 128 |
| `face_sharp_max` | 600.0 |
| `face_sharp_min` | 118.0 |
| `hair_root_drop_min` | 0.006 |
| `hair_tone_spread_min` | 0.098 |
| `hue_entropy_min` | 0.34 |
| `identity_cosine_min` | 0.72 |
| `identity_cosine_warn` | 0.7 |
| `informational` | ['identity', 'cohort', 'age', 'brows', 'iris', 'lips', 'hair_roots', 'hair_tone'] |
| `iris_chroma_min` | 5.0 |
| `iris_expect` | green-hazel |
| `iris_hue_max` | 199.0 |
| `iris_min_ipd_px` | 115 |
| `lip_ratio_min` | 1.2 |
| `min_face_ipd_px` | 100 |
| `required` | ['chroma', 'sharp', 'skin'] |
| `skin_relief_floor` | 0.004 |
| `skin_smooth_max` | 0.34 |
