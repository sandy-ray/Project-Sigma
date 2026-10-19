# Eridant document test packets

Each folder contains the five document files required by the demo. Select all five
files together from **browse files**, or upload one document into each labeled
row. Files are classified from their contents, parsed immediately in the
browser, and never uploaded to the server.

| Folder | Expected deterministic result | Expected findings |
| --- | --- | --- |
| `01_decline_as_presented` | `DECLINE AS PRESENTED` | Critical EBITDA mismatch, high customer concentration, medium operational divergence, high debt-funded growth |
| `02_approve_with_conditions` | `APPROVE WITH CONDITIONS` | Medium customer concentration and high debt-funded growth |
| `03_clean_approve` | `APPROVE` | No material findings |
| `04_needs_further_investigation` | `NEEDS FURTHER INVESTIGATION` | Application legal name/address differs from the state filing, the tax return is marked draft, and prior CDD is unresolved |
| `05_compliance_hold` | `COMPLIANCE HOLD` | Beneficial-owner certification conflicts with the prior CDD record and the state-filed chief executive differs |
| `06_incomplete_resubmission` | Upload validation blocks analysis | The tax return intentionally omits depreciation/Form 4562 support required by the deterministic parser |

Every packet contains:

1. `01_financial_statements.docx`
2. `02_tax_return_1120s.docx`
3. `03_loan_application.docx`
4. `04_state_filing_si550.docx`
5. `05_prior_credit_memo.docx`

The five files follow the original Redwood packet's document families, visual
system, and page rhythm: a nine-page CPA-style financial package, a six-page
1120-S facsimile, a three-page regional-bank credit application, a two-page
SI-550 facsimile, and a three-page prior credit memorandum. The visible pages
retain the supplied packet's typography, rules, form boxes, bank headers, and
sparse continuation-page composition while changing the facts and metrics for
each deterministic scenario. No parser or upload-extraction banner is printed
inside the documents.

The test facts and controls are informed by U.S. commercial-credit, commercial
real-estate, customer-due-diligence, sanctions, and adverse-action guidance.
There is no single public "California regional bank standard," so these files
must not be treated as certified compliance templates or production legal forms.

All names, entities, addresses, and financial figures are fictional and exist
only for parser and decision-engine testing. The IRS and California layouts are
facsimiles rather than official forms.

## CRE sample packet

`cre_01_cedar_grove_refinance` is a fictitious $12.0M refinance of a grocery-anchored
retail center. It contains PDFs 01–11. Use **Load sample CRE file** on the CRE side
of the upload card, or drop the PDFs yourself. Documents 09 (appraisal) and 10
(existing loan agreement) play the bank-file role.

`answer_key/` holds the expected answer and is never served to the browser:
- `12_Cedar_Grove_Bank_Credit_Underwriting_Memo.pdf` is the bank's finished credit
  memo.
- `Cedar_Grove_CRE_Canonical_Truth_Model.xlsx` is the ground-truth model, including
  the planted discrepancy matrix.

Expected deterministic result, matching the truth model's discrepancy matrix:

| Severity | Checks |
| --- | --- |
| Critical | D10 covenant DSCR: certificate 1.34× vs bank 1.244× against a 1.25× minimum |
| High | D08 anchor early-termination right (12/31/2029), D09 $85K roof/HVAC add-back not accepted, D11 $550K affiliate advance missing from the debt schedule, D12 NOI −19% since 2023 |
| Medium | D04 Family Dental expiration 2028 vs 2027, D05 $83K recovery gap, D06 occupancy 90.0% vs ~95% (Suite 200 vacated 8/1/26), D07 appraisal shop-rent assumption |
| Clear | D01 mortgage balance as-of dates, D02 newer $40/SF lease, D03 FreshMart ⇄ FM Retail Operations LLC |

The truth model's appraisal sheet lists a 7.75% cap rate and $1.625M NOI. The
appraisal PDF says 9.00% and $1.836M. The app reads the PDF.
