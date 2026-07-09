# Borehole Extraction Pipeline Audit

Source: page 2 (cover page) bracketed "HOLE NOS." lists from each report in `Borehole Reports/`, cross-checked against `individual borehole logs/` and `results\borehole_stratigraphy_v3.csv`.

## 1. Borehole lists declared per report (page 2)

### 1996-06 — `SI for D-Wall and Barrettes By Bachy dated Jun1996 1.pdf`
> HOLE NOS. DH5-DH51, DH53-DH60, B5, B6, C5

58 holes: DH5, DH6, DH7, DH8, DH9, DH10, DH11, DH12, DH13, DH14, DH15, DH16, DH17, DH18, DH19, DH20, DH21, DH22, DH23, DH24, DH25, DH26, DH27, DH28, DH29, DH30, DH31, DH32, DH33, DH34, DH35, DH36, DH37, DH38, DH39, DH40, DH41, DH42, DH43, DH44, DH45, DH46, DH47, DH48, DH49, DH50, DH51, DH53, DH54, DH55, DH56, DH57, DH58, DH59, DH60, B5, B6, C5

### 1996-07 — `SI for D-Wall and Barrettes By Bachy dated Jul1996 1.pdf`
> HOLE NOS. A5a, B1, B1a, B2, B2a-B2c, B3, B3a-B3c, B4, B4a, C1, C2, C2a, C3, C3a, C4, C6, D1a

21 holes: A5A, B1, B1A, B2, B2A, B2B, B2C, B3, B3A, B3B, B3C, B4, B4A, C1, C2, C2A, C3, C3A, C4, C6, D1A

### 1996-08 — `SI for D-Wall and Barrettes By Bachy dated Aug1996 1.pdf`
> HOLE NOS. P1, P2, P3, P4, P61, P62, P63, P64, B6a, B6b, C6a

11 holes: P1, P2, P3, P4, P61, P62, P63, P64, B6A, B6B, C6A

### 1996-09 — `SI for D-Wall and Barrettes By Bachy dated Sep1996 1.pdf`
> HOLE NOS. DH7, DH19, DH34, DH40, DH42, DH47, DH55

7 holes: DH7, DH19, DH34, DH40, DH42, DH47, DH55

**Total unique boreholes declared across all reports: 90**

---

## 2. Reports vs. split logs (`individual borehole logs/`)

No declared holes are missing a split PDF (including OCR-tolerant matching).

---

## 3. Split logs vs. master CSV (`results\borehole_stratigraphy_v3.csv`)

- Unique hole numbers in split logs: **90**
- Unique hole numbers in master CSV: **90**

Every split log has a corresponding CSV entry — no extraction-stage losses.


---

## 4. Summary

| Check | Result |
|---|---|
| Report → Split logs | Clean |
| Supplementary re-investigation coverage | Clean |
| Split logs → Master CSV | Clean, 90/90 match |

