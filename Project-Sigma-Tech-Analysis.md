# Introductory Overview

(TBD: to include a visual depiction of the overall functionality once the complete document is written.)

# The Document Intelligence Pipeline
The document intelligence pipeline represents the foundational system layer upon which all downstream functionality depends. The quality of output from this pipeline directly determines system reliability. 

The complete document intelligence pipeline comprises the following stages: 

```
ingestion → OCR → classification → extraction
```

Each stage exhibits distinct failure modes, and errors propagate through subsequent stages. Misclassification of documents results in incorrect extraction schema application, leading to data integrity issues downstream. Pipeline design directly determines whether the system maintains reliability and data consistency or proves inherently brittle.

Document data extraction is well-established technology. The central engineering challenge is managing the substantial variability present in real-world document formats and quality.

Community bank borrower packets typically contain hand-typed spreadsheets, scanned PDA outputs, inconsistently formatted tax returns, and facsimile images. Document types span picture formats (e.g., .jpg, .png), office documents (e.g., .docx, .xlsx), and PDFs. Documents may be submitted as individual files, .zip/.tar bundles, or concatenated within single PDF files.

The PRD acknowledges this with its "imperfect scan" synthetic data requirement, but the engineering reality of handling that variability at production quality is substantial.

## Building the Document Intelligence Pipeline

> AWS is used as the reference cloud platform for architecture examples. The architectural patterns and design principles apply across any leading cloud platform.

The pipeline comprises five sequential stages, each with distinct technical considerations. The following sections detail each stage and their integration as a cohesive system.

### Stage 1: Ingestion
Ingestion serves as the system entry point. Files arrive through multiple channels (manual upload, zip bundles, or secure batch transfer) and must be received, stored, and queued for processing in a controlled manner.

The AWS architecture employs S3 for document storage, SQS for processing queues, and downstream processors to execute jobs. Several architectural decisions merit careful consideration:

* Virus scanning must precede all document processing. Most cloud platforms lack native virus scanning; integration with a third-party scanner (open source deployable on Lambda or EC2, such as ClamAV, or commercial solutions like Trend Micro's S3 scanning) is required. For financial services applications, this capability is non-negotiable.
* File type normalization must occur at ingestion. Borrowers submit PDFs, Word documents, Excel spreadsheets, and images. Some submitted files are scanned image PDFs lacking a text layer. The system must reliably detect file type independent of filename extensions, validate file integrity, and route to appropriate handlers. For example, AWS Textract accommodates both native-text and image PDFs, but the routing logic determining processing path resides in this stage.
* Zip bundle handling introduces operational complexity. Upon zip arrival, the system must extract contents, enumerate member files, validate each, and generate individual processing jobs while maintaining provenance linkage to the originating packet. Malformed or nested archives further complicate this logic.
* Metadata capture at ingestion (filename, upload timestamp, uploader identity, file size, MIME type, packet association) must be recorded durably at entry. This establishes the foundational provenance chain.

### Stage 2: OCR and Text Extraction

This stage produces the text layer upon which all downstream processing operates. Extraction errors are permanent without reprocessing; therefore, mechanisms to minimize errors at this stage are essential.

Amazon Textract serves as the primary AWS service for this stage. It processes both native-text PDFs and scanned documents, with specialized capabilities for table and form extraction. Textract provides multiple distinct APIs with different applicability:

* **DetectDocumentText** — raw text extraction, line by line. Fast, cheap, but loses structure entirely.
* **AnalyzeDocument with FORMS** — extracts key-value pairs. Useful for structured forms like personal financial statements.
* **AnalyzeDocument with TABLES** — extracts tabular data preserving row/column structure. Critical for financial statements, debt schedules, A/R aging reports.
* **AnalyzeExpense** — specialized for invoices and receipts; less relevant here but worth knowing.
* **AnalyzeDocument with QUERIES** — you ask targeted questions about a document and Textract finds the answer region. This is interesting for targeted field extraction on well-structured documents.

Commercial credit packets typically require multiple extraction modes on single documents. Tax returns contain both forms and tables. Debt schedules are predominantly tabular. Prior credit memos consist primarily of narrative text. The OCR orchestration layer must determine appropriate Textract API calls per document type, requiring preliminary document classification before full OCR orchestration.

> **Textract Limitations**
> Real-world Textract limitations are well-documented: (a) Performance is strong on clean, well-formatted PDFs but degrades with low-resolution scans, skewed pages, and non-standard fonts; (b) Table extraction is functional but imperfect—merged cells, nested tables, and multi-page tables introduce errors; (c) The service lacks financial document semantic understanding, extracting text without domain context; (d) Processing at scale can be slow and costly for large documents.

Alternative OCR engines are available, including Google Cloud Vision through API integration or open-source Tesseract deployed on EC2/ECS. 

**OCR quality scoring** represents a necessary engineering investment. Before extracted text advances downstream, a confidence signal must be established—either from OCR engines' native word-level confidence scores or derived metrics based on character error rates, word count validity, or table structure coherence. Low-confidence OCR output must be flagged rather than silently passed downstream.

**Table extraction** requires special attention, as credit packets contain substantial critical data in tabular form—financial statements, accounts receivable aging, debt schedules. Textract returns table output as cell matrices. Converting these into semantically meaningful structures (identifying line items, column headers, and data significance) represents a non-trivial parsing challenge between OCR and extraction stages.

**Human-review routing** represents an integral component of this stage, flagging low-confidence OCR output for analyst validation.

### Stage 3: Document Classification

Following text and structure extraction, each document must be classified into the defined taxonomy (prior credit memo, tax return, debt schedule, etc.) to enable appropriate extraction schema application.

Classification represents a machine learning problem with several viable architectural approaches:

* **Embeddings-based classification** likely represents the optimal primary approach for Project Sigma. Document text or meaningful excerpts (opening tokens, table of contents, key pages) are converted to embedding vectors using a text embedding model, then classified against reference embeddings or a trained classifier. This approach generalizes effectively to document variants and proves robust to formatting variations.
* **Fine-tuned classifier**—a small text classification model fine-tuned on labeled document type examples—can achieve high precision with sufficient labeled training data. MVP phase synthetic data may lack sufficient labeled variance for reliable fine-tuning; this approach becomes viable post-MVP following procurement of real document diversity from design partners.
* **LLM-based fallback**—for ambiguous or low-confidence documents, submitting initial pages to large language models with classification prompts provides a practical fallback. While more costly and slower, this approach accommodates document types not cleanly categorized and returns confidence signals with reasoning. The PRD explicitly specifies this pattern.

As with text extraction, **confidence thresholds and human review routing** serve as critical operational elements. Every classification must produce a confidence score. Documents below threshold are routed to human review queues, presented in the UI as "classification uncertain, please confirm." This represents designed behavior maintaining system trust, not a failure mode.

*On AWS, classification workflows run as Lambda functions or ECS tasks triggered via SQS, invoking Bedrock for embeddings and LLM classification, with results and confidence scores persisted to document records in DynamoDB or RDS.*

**A practical consideration**: classification accuracy depends substantially on selecting appropriate text segments. A 40-page tax return contains extensive content; embedding all text proves inefficient. Only the most discriminative regions (opening page, form headers, key identifiers) should be embedded. Text selection decisions materially affect classification accuracy.

### Stage 4: Extraction

Extraction represents the most complex stage, as extraction logic is entirely document-type dependent, with each type exhibiting distinct schemas, structural patterns, and failure modes.

The core architectural requirement is differentiated extraction strategies per document type, spanning a spectrum from highly structured to unstructured:

* **Highly fixed-structure documents** (standardized forms) feature well-known field locations. Combining Textract FORMS/QUERIES with deterministic parsing rules achieves high precision. For example, Form 1120 Line 1 consistently represents gross receipts. Such mappings can be hard-coded with extracted values validated against expected data types and ranges, achieving high-confidence extraction without LLM involvement.
* **Semi-fixed-structured documents** (company-prepared financials, debt schedules, accounts receivable aging) exhibit consistent structure (table rows, column headers) with variable formatting (labeling conventions, row ordering, presentation choices differ across sources). Textract table extraction provides structural foundation; a semantic matching layer mapping extracted headers to canonical schemas is required. Lightweight NLP or embedding-based matching provides value here.
* **Narrative/unstructured documents** (prior credit memos, borrower applications, operating agreements, management narratives) lack consistent structure. These represent the clearest use case for LLM-based extraction. Document text is injected into carefully designed prompts requesting extraction of specific fields in defined JSON schemas, with rigorous output validation. Prompt engineering and schema validation constitute the quality-critical elements.

Additional consideration:
* **LLM-based extraction**: Extraction prompts must employ structured output, requesting JSON conforming to predefined schemas with rigorous validation. The system must handle cases where models cannot confidently extract fields (returning null with low-confidence flags, not hallucinated values). System prompts require explicit specification of: field absence handling, confidence semantics, and valid versus uncertain value criteria.
* **Extraction confidence** must be a first-class output design element. Every extracted field must carry: value, confidence score, source text span (actual document text supporting extraction), and page/section reference. These elements power the evidence viewer in the user interface and feed the provenance system.
* **Financial normalization** represents a significant extraction sub-problem. Dollar amounts appear in varied formats ($1,234,567 vs 1234567 vs $1.23M vs parenthetical negatives). Dates use multiple formats. Percentages may be expressed as decimals. A normalization layer converting all extracted values to canonical types before data model entry is required. This normalization must be deterministic and auditable, not implicitly performed by LLMs.

### Pipeline Orchestration

Executing the preceding stages requires explicit orchestration. On AWS, AWS Step Functions provides the appropriate choice. It enables pipeline definition as an explicit state machine—ingestion → OCR → classification → extraction → completion—with branching for document type routing, error handling with retries, human review wait states, and parallel processing for multi-document packets. Visual workflow representation aids development debugging.

The orchestration layer manages:
* **Parallel processing** — multi-document packets are processed in parallel rather than sequentially. Orchestration distributes classification and extraction jobs in parallel, aggregating results upon complete packet processing.
* **Partial failures** — when OCR fails on individual documents within a packet, remaining documents continue processing normally. Failed documents are routed to human review. Step Functions provides built-in handling for this scenario.
* **Human review interruptions** — documents flagged for classification review cause pipeline pause, analyst notification, and resumption upon confirmation or correction. Step Functions' wait-for-callback pattern addresses this requirement precisely.
* **Retry logic** — OCR engine calls may fail transiently; LLM API calls may time out. The orchestration layer requires configurable retry policies with exponential backoff, distinguishing transient failures (eligible for retry) from permanent failures (route to human review).

### The Critical Cross-Cutting Concern: Storage Architecture

Across all pipeline stages, the system produces multiple artifact types requiring durable storage and logical linkage:

* **S3**: raw document files, OCR output (raw Textract JSON), extracted text
* **DynamoDB or RDS**: document metadata, classification results, extracted facts with provenance, processing status
* **Provenance linkage**: every extracted fact must reference its source location in raw OCR output, which references the source document in S3

> **DynamoDB vs. RDS selection** requires careful consideration. DynamoDB provides scalability and minimal operational overhead; however, schema flexibility beneficial during early development becomes a constraint liability as data models mature. PostgreSQL (RDS or Aurora Serverless) provides relational integrity naturally enforcing the provenance chain—foreign key constraints from extracted facts to source documents are database-enforced rather than application-managed. For systems where data integrity represents a trust requirement, PostgreSQL operational overhead proves justified.

### Complete Architecture Overview

Integrated across all stages, the AWS-native pipeline architecture takes the following form:

```text
    Upload 
    → S3 
    → Lambda (virus scan + file type detection)
    → SQS (processing queue)
    → Step Functions (pipeline orchestrator)
        ├── Textract (OCR, async job)
        ├── Bedrock (classification embeddings + LLM fallback)
        ├── Extraction workers (ECS tasks or Lambda)
        │     ├── Deterministic parsers (structured docs)
        │     ├── Semantic matchers (semi-structured)
        │     └── Bedrock LLM extraction (narrative docs)
        ├── Normalization layer
        └── Provenance writer → RDS/Aurora
```

Monitoring infrastructure provides operational metrics via CloudWatch (processing times, error rates, queue depths) and custom quality signals (OCR confidence distribution, classification confidence distribution, extraction field coverage).

### Critical Design Principles

Three principles should govern all pipeline design decisions:

* **Fail loudly, not silently**. Documents that cannot be classified must route to human review rather than receive incorrect assignments. Low-confidence extractions must be flagged rather than passed as authoritative. Silent failures downstream destroy trust substantially more than explicit gaps.

* **Provenance is not optional**. Every pipeline artifact—OCR text, classification results, extracted facts—must carry references to its source. This represents an architecture-level design constraint, not an afterthought feature.

* **Quality measurement requires parallel development with the pipeline**. From initial labeled synthetic documents, the system must measure precision/recall against ground truth. Building the pipeline first and measurement infrastructure second creates blind spots during critical calibration.


# The Normalized Data Model and Reconciliation Engine

> **NOTE: This is an initial thought regarding this capability. Needs to be discussed further to finalize.**

Precision regarding the problem this element solves is essential, as its complexity is substantial and frequently underestimated.

The pipeline produces a collection of extracted facts, each annotated with *source document*, *confidence score*, and *provenance reference*. At this stage, the system possesses fundamentally a structured collection of potentially conflicting claims regarding the same borrower. The normalized data model and reconciliation engine transforms this collection into a single coherent, conflict-aware, evidence-backed representation of borrower financial reality. Downstream components — the exception engine, the memo generator, the evidence viewer — operate on this canonical representation. The quality of this reconciliation directly determines whether the system functions as a genuinely useful credit intelligence tool or remains a document viewer with limited analytical capability.

## The Canonical Data Model

The initial design challenge requires defining the canonical representation of a borrower — the schema to which all extracted facts ultimately map.

**The model must hold multiple values for the same field simultaneously.** This represents a fundamental departure from conventional financial data model design. Traditional database schemas assign a single field for revenue. Project Sigma requires a revenue field capable of simultaneously holding: $9.32M from company financials, $9.05M from the tax return, and a narrative reference of "approximately $9M" from the prior credit memo—each with distinct source, confidence score, and extraction timestamp. The canonical model functions not as a resolved record but as a structured collection of competing claims with a proposed resolution overlay.

**The model must be organized by semantic concept rather than by document source.** This represents the second fundamental departure from naive approaches. Organizing data as "document X claims Y" is structurally simple but renders reconciliation intractable. The model must instead organize around **financial concepts** (revenue, EBITDA, total debt, ownership percentages, guarantor net worth), with each concept maintaining a set of sourced values. Documents function as evidence references rather than as organizing principles.

**The schema comprises multiple conceptual layers requiring distinct treatment:**

> **NOTE: Based on some research, checking with AI chatbots, etc., it appears the data elements required to be captured are as below. This is not an AI capability, it instead requires much depth in domain understanding - personally, my confidence on the contents of this section is low; to be validated through design-partner discovery conversations. - Atul**

* The **entity layer** captures borrower identity—legal name, EIN, business type, address, ownership structure, and guarantors. These fields present distinct reconciliation challenges (operating agreement specifies 55/45 ownership; application specifies 60/40) but remain discrete and categorical rather than continuous financial values.

* The **financial performance layer** captures income statement concepts across periods — revenue, COGS, gross profit, operating expenses, EBITDA, and net income — typically spanning two to three years of historical data plus interim periods. Each period-concept cell maintains multiple sourced values.

* The **balance sheet layer** captures point-in-time financial position—total assets, total liabilities, working capital, specific asset categories (A/R, inventory, PP&E), and specific liability categories (current debt, long-term debt). Multiple sources populate each cell.

* The **debt and obligation layer** captures existing borrowing structure — lender name, original balance, current balance, maturity date, payment terms, and collateral — typically sourced from debt schedules, bank statements, and prior credit memos. This layer presents among the most challenging reconciliation targets because debt items lack natural identifiers; matching records across documents requires fuzzy entity resolution based on lender similarity, balance magnitude, and term alignment rather than shared key values.

* The **collateral layer** captures credit facility security—A/R eligible for borrowing base, inventory, equipment, and real estate—with values sourced from A/R aging reports, borrowing base certificates, and prior memos.

* The **relationship and policy layer** captures credit structure—facility type, amount, maturity, covenants, prior exceptions, and relationship history—derived primarily from prior credit memos and borrower applications.


## The Conflict Group Structure

The Conflict Group represents the most critical structural element in the data model. Although the PRD identifies this element, precision regarding its contents and operational mechanics proves essential.

A Conflict Group is created when two or more sourced values for an identical field-period combination diverge beyond the defined tolerance threshold. It contains:

**Field identity**—the canonical field subject to conflict (e.g., `revenue.2023.annual`).

**Competing values**—each with source document, extraction confidence, specific text span, and extraction method (deterministic parser, semantic matcher, or LLM).

**Source precedence determination**—which value prevails according to the configured hierarchy for this field category and the rationale for that determination. This represents deterministic reconciliation engine output, not subjective judgment.

**Proposed normalized value**—the value consumed by downstream computation (exception rules, financial ratios, memo generation). This represents the precedence winner unless overridden by analyst intervention.

**Conflict severity signal**—the magnitude of discrepancy. A 0.3% revenue difference between tax return and company financials represents expected definitional variance. A 15% difference constitutes material conflict. The severity signal feeds directly into the exception engine.

**Resolution state**—unresolved, analyst-accepted, analyst-overridden (with override value and supporting note), or flagged-for-follow-up. The workflow layer manages this state.

A critical design consideration: **not every multi-source field constitutes a conflict.** When multiple documents report identical values, this represents corroboration—high confidence and source alignment. The model must represent corroboration explicitly as the positive signal that increases value confidence. Conflict represents the negative signal that generates exceptions. Both phenomena require explicit representation.


## The Reconciliation Engine

The reconciliation engine is the process that consumes extracted facts from the pipeline and produces the populated canonical model with conflict groups. It executes after all documents within a packet complete pipeline processing.

**Step 1: Field mapping.** Every extracted fact requires mapping to a canonical field. While conceptually straightforward — "revenue maps to revenue" — this constitutes a semantic matching problem in practice. The tax return's "Gross receipts or sales (line 1a)" maps to `revenue.gross`. Company-prepared financials may label the identical concept as "Net Revenue," "Total Sales," or "Revenue from Operations" depending on preparation conventions. The mapping layer requires a **semantic field dictionary** that maps document-type-specific labels to canonical field identifiers. This dictionary comprises system configuration requiring maintenance as new document variants are encountered.

**Step 2: Period alignment.** Financial values lack meaning without their temporal context. Revenue figures are comparable only when covering identical periods. The reconciliation engine must extract, normalize, and align periods—fiscal year versus calendar year, interim periods, trailing twelve months—prior to value comparison. Period misalignment represents a frequent source of spurious conflicts: the tax return covers fiscal year ending March 31; company financials cover calendar year ending December 31; the engine incorrectly identifies conflict between figures measuring distinct twelve-month windows.

**Step 3: Unit normalization.** Dollar amounts require consistent units prior to comparison. Some documents express values in thousands; others in full dollars; some mix both within the same page. The normalization layer must detect and resolve unit differences before comparison.

**Step 4: Tolerance evaluation.** For each field-period combination containing multiple values, the engine evaluates whether value differences exceed the configured tolerance threshold. Values within threshold indicate corroboration or acceptable variance; no conflict group is created. Values exceeding threshold trigger conflict group creation and exception queueing. Tolerance values constitute bank-level configuration, as institutions maintain distinct policies regarding meaningful discrepancy thresholds.

**Step 5: Precedence resolution.** For each conflict group, the engine applies the source-of-truth hierarchy for that field category to select the proposed normalized value. The hierarchy must be field-category-specific (for revenue: tax return > audited financials > company-prepared financials > application narrative) and configurable per institution. The conflict group retains both the selected value and the selection rationale (which hierarchy rule applied).

**Step 6: Derived value computation.** Following normalization, derived values are computed deterministically from normalized values: DSCR, leverage ratios, working capital, borrowing base capacity, customer concentration percentages. Derived values function as first-class canonical model fields, with computation inputs recorded for provenance. This computation occurs in the reconciliation engine rather than exception engine, enabling the exception engine to treat derived values identically to extracted fields for threshold evaluation.


## The Hard Problems

Three fundamentally challenging problems merit specific attention prior to any implementation decisions.

**Hard problem 1: Entity and debt record matching.** Matching debt items across documents presents no clean algorithmic solution. A prior credit memo references "First National Bank revolving credit line, $850K." The debt schedule displays "FNB Revolver - $847,500." Bank statements show payments to "First National Bk." These almost certainly represent the same obligation, yet matching requires fuzzy entity resolution—lender name similarity, balance magnitude within tolerance, and loan type alignment. Implementation errors produce either false conflicts (identical debt counted multiple times) or missed conflicts (distinct debts treated as identical). LLM-assisted matching—"do these debt records reference the same obligation?"—provides genuine value in this domain, with deterministic fallback for high-confidence cases and human-review flagging for ambiguous instances.

**Hard problem 2: Temporal context of the prior credit memo.** The prior credit memo occupies a unique role as both a source of facts (containing borrower financial data from prior review) and a source of narrative claims (management commentary, analyst observations, relationship context). Facts extracted from the memo require annotation with memo review date rather than current review date, enabling the reconciliation engine to distinguish historical data from current data. Narrative claims require separate treatment—they feed narrative contradiction exception logic rather than financial field reconciliation.

> I am not sure I have a good grasp on what the 'prior memo' is for. Hence while I belive the above is relevant, I need confirmation from the team on it.

**Hard problem 3: Handling structural differences in financial statements.** Income statements lack uniform structure. Manufacturers present COGS and gross profit. Service businesses may present direct costs via alternative structures. Pass-through entities (LLC, S-corp) exhibit different tax return structure than C-corps. The canonical model must accommodate these structural variations without imposing a rigid schema unsuited to real-world documents. The appropriate approach likely employs a **two-layer schema**: a flexible extraction layer preserving document-specific structure, and a canonical layer mapping to standardized concepts where unambiguous mappings exist, with unmapped items retained as document-specific fields.


## AWS Architecture for This Element

On AWS, this element occupies the intermediary position between the pipeline (producing extracted facts) and the exception engine and application layer (consuming the canonical model).

**PostgreSQL on RDS or Aurora** represents an appropriate persistence choice, as relational integrity constraints naturally enforce the provenance chain. The schema centers on core tables: `documents`, `extracted_facts` (with source, confidence, text span), `canonical_fields` (schema definition), `fact_mappings` (extracted fact → canonical field mapping), `conflict_groups` (reconciliation output), and `normalized_values` (proposed field-period resolution). Table relationships constitute the data model.

**The reconciliation engine** comprises a processing component best implemented as a Python service on **ECS** or as a **Lambda function** for smaller packets, triggered by Step Functions upon completion of all pipeline stages for a packet. As a fundamentally batch-oriented data processing operation rather than long-running service, task-oriented execution architecture aligns appropriately.

**For semantic field mapping and debt record matching**, Bedrock embeddings provide the appropriate tool. Extracted labels ("Gross receipts or sales, line 1a") and canonical field descriptions are embedded, with best-match identification via cosine similarity. This approach exhibits speed, cost efficiency, and robust generalization to new document variants without retraining.

**Reconciliation result caching** critically impacts user experience. When analysts access a packet in the UI, they expect immediate canonical model and conflict group access rather than waiting for reconciliation engine re-execution. Reconciliation output should persist as complete database snapshots immediately following engine execution, with versioning such that subsequent runs (triggered by analyst corrections or new document uploads) produce new snapshots rather than overwriting previous versions.

## The Key Design Principle for This Element

The reconciliation engine must function as **a witness, not a judge**. It observes all evidence, organizes evidence, applies mechanical rules to propose resolution, and renders every process step visible and reversible. The engine must never silently discard conflicting values, never apply judgment unencoded in configurable rules, and never produce normalized values whose derivation cannot be fully traced. Opaque engine decision-making directly undermines analyst trust—the product's foundational value proposition.

This element directly feeds the next two — the exception engine consumes the normalized values and conflict groups to generate exceptions, and the provenance system uses the fact mapping and source references to power the evidence viewer.



# The Exception Engine Design

> **NOTE: This is an initial thought regarding this capability. Needs to be discussed further to finalize.**

> **This is also not an AI capability, it instead requires much depth in domain understanding - personally, my confidence on the contents of this section also is low; to be validated through design-partner discovery conversations. - Atul**

Before getting into the architecture, it's worth being precise about the engine's exact role in the system. The exception engine sits downstream of the reconciliation engine and consumes a fully populated canonical model — normalized values, conflict groups, derived metrics, and resolution states. Its job is to evaluate that model against a set of rules and produce a ranked, prioritized list of exceptions that an analyst needs to act on. It does not extract, reconcile, or judge — it evaluates and signals.

That distinction matters because it defines the engine's design constraints precisely: it must be **deterministic**, **configurable**, **transparent**, and **noise-controlled**. Every one of those constraints creates real engineering tension that needs to be thought through before implementation begins.

## The Three-Layer Rule Architecture

The PRD identifies eight exception types which is helpful, but the organizing principle for engineering purposes is to think about the rule set in three distinct layers, each with different engineering requirements and different calibration challenges.

**Layer 1: Universal Rules**

These apply to every borrower packet regardless of bank, loan type, or jurisdiction. They are binary and require no configuration — either the condition is met or it isn't.

Missing document rules fall here. If the document checklist for a given loan type requires a business tax return and none was classified in the packet, that is an exception. The rule is: required document type X is absent → exception of type "missing document" at configured severity. The document checklist itself is configurable per loan type and per bank, but the rule logic is universal.

Basic tie-out failures also fall here. If the accounts-receivable (A/R) aging report total doesn't match the A/R line on the balance sheet within any reasonable tolerance, that's a tie-out failure regardless of which bank is using the system. The reconciliation engine has already computed both values and flagged the conflict group — the exception engine's job here is simply to recognize that certain conflict groups of this type constitute a specific exception category.

Stale document rules fall here too. If a document's date is beyond the configured freshness threshold, it's stale. Binary evaluation, configurable threshold, universal logic.

**Layer 2: Configurable Policy Rules**

These rules have universal logic but bank-specific parameters. The rule structure is identical across institutions; the threshold values differ.

Variance tolerance rules are the clearest example. The rule is: if the normalized value for field X differs from source Y by more than threshold T, generate an exception. The rule structure is fixed. T is configured per field category per bank. One bank may treat a 3% revenue variance as acceptable; another may flag anything above 1%.

Freshness thresholds are similar. The rule structure is: document dated more than N days before review date → stale document exception. N is bank-configured, and may vary by document type within the same bank (tax returns might have a longer acceptable window than interim financials).

Severity mappings also live here. The same exception type might be Material at one bank and Administrative at another depending on their risk appetite and credit policy. The severity mapping table is bank-level configuration that the exception engine applies when assigning severity to a generated exception.

**Layer 3: Analytical Rules**

These are the most complex and the most valuable — they require computed financial metrics and evaluate them against defined thresholds. They are also the most likely to produce meaningful exceptions that wouldn't be caught by a human analyst doing a quick first pass.

DSCR evaluation is the canonical example. The reconciliation engine has computed DSCR from normalized cash flow and normalized debt service figures. The exception engine evaluates: is computed DSCR below the configured minimum covenant threshold? If yes, this is an exception. If the DSCR computation involved low-confidence inputs, the exception should note that — the reliability of the exception is partly a function of the reliability of the inputs.

Borrowing base coverage is another example directly from the Harborview scenario. The engine computes eligible collateral from the A/R aging (applying advance rate, excluding ineligible receivables) and compares to the requested facility amount. If eligible collateral supports $1.42M and the requested revolver is $1.85M, that's a Critical exception. The math is deterministic; the advance rate and eligibility criteria are configurable.

Customer concentration follows the same pattern. The engine computes the percentage of A/R attributable to the single largest customer from the aging report. If that percentage exceeds the configured concentration threshold, exception generated. If the prior credit memo's narrative states "no material concentration" and the computed percentage exceeds the threshold, that's a narrative contradiction exception — a more specific and higher-severity variant.

Leverage ratio, working capital adequacy, and trend analysis (year-over-year revenue decline, margin compression) all follow the same pattern: deterministic computation from normalized values, threshold comparison from bank configuration, exception generation if threshold is breached.

## The Exception Data Structure

Every exception the engine generates needs to carry a precise set of fields. This is not just a data model question — the structure of an exception determines what the analyst sees, what the evidence viewer can display, and what the audit trail records.

**Exception identity and classification:**
- Unique exception ID
- Exception type (from the PRD's taxonomy: missing document, stale document, field inconsistency, tie-out failure, narrative contradiction, analytical threshold breach, low-confidence extraction, source precedence conflict)
- Severity (Critical, Material, Administrative, Informational)
- Generating rule identifier — which specific rule produced this exception

**The evidence chain:**
- The canonical field(s) involved
- The normalized value(s) that triggered the rule
- The conflict group reference if applicable
- The specific source documents involved
- The text span references from OCR output

**The analytical context:**
- For threshold breach exceptions: the computed value, the threshold, and the margin of breach
- For conflict exceptions: all competing values, their sources, and the precedence determination
- For narrative contradiction exceptions: the narrative claim, the computed or extracted value that contradicts it, and both source references

**Confidence qualification:**
- Input confidence — the aggregate confidence of the extracted values that fed the rule evaluation
- Exception confidence — how confident the engine is that this is a genuine exception versus a false positive, which is partly a function of input confidence and partly a function of rule specificity

**Resolution state:**
- Unresolved (initial state)
- Acknowledged (analyst has seen it, no action yet)
- Accepted (analyst confirms this is a real exception, it will appear in the memo)
- Resolved with explanation (analyst has provided context that explains the discrepancy — it stays in the record but is marked resolved)
- Overridden (analyst disagrees with the exception — requires a note explaining why)
- Escalated (flagged for credit officer review)
- Follow-up requested (a question has been sent to the relationship manager or borrower)

## The Ranking and Prioritization Logic

> **This my perception of the ranking. Please review.**

Generating exceptions is only half the job. The other half is presenting them in an order that maximizes analyst efficiency and minimizes the cognitive load of working through a long exception list.

The naive approach — sort by severity descending — is necessary but not sufficient. A packet with twelve Critical exceptions all listed in a flat list is still overwhelming. The ranking logic needs to be more sophisticated:

**Primary sort: severity.** Critical exceptions always appear first, then Material, then Administrative, then Informational.

**Secondary sort within severity: analytical exceptions before documentary ones.** A Critical analytical exception (borrowing base shortfall, DSCR breach) is more decision-relevant than a Critical missing document. The analyst needs to understand the financial picture before evaluating whether a missing document matters.

**Tertiary sort: exception confidence.** Within the same type and severity, higher-confidence exceptions should appear before lower-confidence ones. A tie-out failure computed from high-confidence extracted values is more actionable than one computed from low-confidence LLM extractions.

**Grouping by topic.** Related exceptions should be visually grouped even if they have different severities. The three debt-related exceptions in the Harborview scenario (debt mismatch across three sources, borrowing base shortfall, cash flow contradiction) are thematically connected — presenting them together helps the analyst understand the pattern rather than treating each in isolation.

> Just to go a bit deeper into how the topic can be determined, here is my current thought - Maintain a configurable mapping that groups exception types (not rules) by topic. When the exception engine generates an exception, it assigns both the exception type and (via lookup) the topic. Following table gives some example entries for such mappings --

> | exception_type          | field_category     | topic |
> |------------------------|--------------------|-------------------|
> | field_inconsistency     | debt.total         | debt_structure |
> | analytical_threshold    | debt.coverage      | debt_structure |
> | analytical_threshold    | leverage_ratio     | profitability |
> | ...  | ... | ... |

**Suppression of redundant exceptions.** If the reconciliation engine has already created a conflict group for a revenue discrepancy, and the exception engine generates both a "field inconsistency" exception and an "analytical threshold breach" exception that both trace to the same underlying conflict, those should be linked and presented as one composite exception rather than two separate items. Redundant exceptions are a primary source of false-positive noise.

## The Noise Control Problem

This is the engine's hardest calibration challenge and the PRD's most significant risk. The ≤25% false-positive target is important but ambitious, and hitting it requires deliberate engineering rather than hoping the rules are well-tuned.

**Tolerance calibration is iterative.** The initial tolerance thresholds will be wrong. They'll be set based on reasonable assumptions about what constitutes a meaningful discrepancy, but real document packets will reveal that some thresholds are too tight (generating noise on normal variance) and some are too loose (missing real exceptions). The system needs a feedback mechanism — analyst override patterns and explicit false-positive flags — that feeds back into threshold calibration over time. This is not something you can fully design upfront; it requires a closed loop between analyst behavior and rule parameters.

**Definitional variance is not conflict.** Many apparent discrepancies between sources are expected and explainable by definition differences, not by actual inconsistency. Tax return revenue excludes certain items that GAAP financials include. Interim financials may use different accrual conventions than year-end audited statements. The exception engine needs to be aware of these known definitional differences and suppress exceptions that fall within expected definitional variance bands for specific field-source combinations. This is a domain knowledge problem — the system needs to encode credit analysis conventions, not just apply generic thresholds.
> While I highlight it as different from Tolerance caliberation, it is somewhat related. There can be a tolerance map for different sources which the system can use for this purpose --

> | field_category | source_a           | source_b              | expected_variance_band | reason |
> |----------------|--------------------|-----------------------|------------------------|-------------------------------- |
> | revenue         | tax_return         | gaap_financials       | 0-5%                   | Tax return excludes certain GAAP adjustments; timing differences |
> | revenue         | interim_financials | year_end_audited      | 1-3%                   | Different accrual conventions; cutoff timing |
> | ar_total        | ar_aging_report    | balance_sheet         | 0-2%                   | Minor posting differences, timing |
> | ebitda          | company_financials | tax_return            | 5-8%                   | Tax return adds back non-deductible items |

> Open question - does this belong in the Reconciliation Engine, or in Exception Engine? There are pros and cons for both. I am thinking Reconciliation Engine should NOT suppress it, and let Exception Engine be configured to ignore it as necessary.

**Confidence-gated exception generation.** Exceptions generated from low-confidence extracted values are themselves low-confidence. A field inconsistency exception where both values were extracted by LLM from narrative text with 60% confidence is qualitatively different from one where both values were extracted deterministically from structured tax forms. The engine should either suppress exceptions below a minimum input confidence threshold, or downgrade their severity automatically, with a clear signal to the analyst about why.

**The false-positive feedback loop.** When an analyst marks an exception as overridden or as a false positive, that signal needs to be captured in a structured way — not just as a free-text note, but as a tagged event that records which rule generated the exception, what the input values were, and what the analyst's override rationale was. Over time, these signals should feed a rule calibration review process. This won't be automated in MVP, but the data capture needs to be there from day one so that the calibration work can happen based on real analyst behavior.

## The Narrative Contradiction Exception — A Special Case

This exception type deserves its own treatment because it's architecturally distinct from all others and it's one of the highest-value exception types in the product.

A narrative contradiction occurs when a claim made in a narrative document (the prior credit memo, the borrower application, management commentary) is contradicted by a computed or extracted value. The Harborview examples are clear: the prior memo says "no material customer concentration" but the A/R aging shows 18% to one customer. The borrower application narrative implies strong liquidity but the working capital computation shows it's under pressure.

Detecting these requires a two-step process that spans the reconciliation engine and the exception engine:

**Step 1: Narrative claim extraction.** During the pipeline's extraction stage, the LLM must be prompted not just to extract structured fields but to identify and extract specific assertional claims from narrative text — claims about concentration, profitability trends, relationship depth, collateral quality, management strength. These claims need to be stored as a distinct fact type in the canonical model, tagged as narrative assertions rather than financial values.

> It will be important to either explicitly ennumerate the specific assertions to be extracted, or the characteristics of the assertions that are relevant for the domain of the problem this solution concerns itself with.

**Step 2: Contradiction evaluation.** The exception engine compares each narrative assertion against the relevant computed or extracted value. This comparison is itself a judgment call — "no material concentration" versus 18% — that requires either a rule encoding what "material concentration" means numerically, or an LLM evaluation that assesses whether the quantitative evidence contradicts the narrative claim.

> as noted in the sidebar above, along with ennumerating the specific assertions to extract, semantic equivalence of the assertion to a quantified value will be required. Just a clarification, this can't be left to the LLM to judge that 18% is or isn't "material concentration".

This is one of the places where LLM involvement in the exception engine is justified — not for making the exception determination, but for evaluating semantic consistency between a narrative claim and a quantitative finding. The LLM's output should be a structured assessment (contradiction detected / not detected / ambiguous) with a confidence score, and the exception engine's rule then determines whether that assessment clears the threshold for exception generation. The LLM evaluates; the rule decides.

## AWS Architecture for the Exception Engine

The exception engine is architecturally simpler than the reconciliation engine because it's primarily a rule evaluation process over a well-structured data model.

**The rule engine itself** is most naturally implemented as a Python service — a set of rule evaluator classes, one per exception type, each taking the canonical model as input and returning a list of candidate exceptions. This runs on **ECS or Lambda**, triggered by Step Functions when the reconciliation engine completes. It's a stateless computation — given the same canonical model, it always produces the same exceptions — which makes it easy to test, debug, and re-run when rules are updated.

**Rule configuration storage** needs to live in a structured, versioned store. Bank-level configuration (thresholds, severity mappings, document checklists, freshness windows) should be stored in **RDS** alongside the rest of the relational data model, with a versioning mechanism so that changes to a bank's configuration don't retroactively alter the exception evaluation of previously processed packets. When you re-evaluate a packet, you should be able to specify which configuration version was in effect at the time of the original review.

**The LLM component for narrative contradiction** runs via **Bedrock**, with the narrative assertion and the relevant quantitative finding injected into a structured prompt. The output is stored as a typed fact — not a free-text analysis — and the exception generation rule operates on that structured output.

**Exception storage** in **RDS** with full relational integrity — exceptions link to canonical fields, conflict groups, source documents, and extracted facts via foreign keys. This is the provenance chain for exceptions, and it needs to be as rigorous as the provenance chain in the pipeline.

**Re-evaluation triggers** need to be designed explicitly. When an analyst overrides a normalized value in the reconciliation engine, the exceptions that depend on that value need to be re-evaluated. When a new document is uploaded to an existing packet, affected exceptions need to be flagged for re-evaluation. This re-evaluation logic — which exceptions are invalidated by which changes to the canonical model — is a dependency graph problem that needs to be modeled carefully. Getting it wrong means stale exceptions persisting in the UI after the underlying data has changed.

## The Key Design Principle for This Element

The exception engine's job is to be **a signal, not a checklist**. The distinction matters enormously for analyst adoption. A checklist produces a complete list of everything that could be wrong. A signal produces a ranked, evidence-backed, noise-controlled set of the things most likely to actually matter for this credit decision. The engineering discipline required to be a signal rather than a checklist — tolerance calibration, redundancy suppression, confidence gating, analytical prioritization — is harder than building the rules themselves. But it's what determines whether analysts get a high value from the tool or learn to ignore it due to unfocussed verbosity.