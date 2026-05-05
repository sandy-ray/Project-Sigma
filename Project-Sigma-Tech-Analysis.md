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

The **entity layer** captures borrower identity—legal name, EIN, business type, address, ownership structure, and guarantors. These fields present distinct reconciliation challenges (operating agreement specifies 55/45 ownership; application specifies 60/40) but remain discrete and categorical rather than continuous financial values.

The **financial performance layer** captures income statement concepts across periods — revenue, COGS, gross profit, operating expenses, EBITDA, and net income — typically spanning two to three years of historical data plus interim periods. Each period-concept cell maintains multiple sourced values.

The **balance sheet layer** captures point-in-time financial position—total assets, total liabilities, working capital, specific asset categories (A/R, inventory, PP&E), and specific liability categories (current debt, long-term debt). Multiple sources populate each cell.

The **debt and obligation layer** captures existing borrowing structure — lender name, original balance, current balance, maturity date, payment terms, and collateral — typically sourced from debt schedules, bank statements, and prior credit memos. This layer presents among the most challenging reconciliation targets because debt items lack natural identifiers; matching records across documents requires fuzzy entity resolution based on lender similarity, balance magnitude, and term alignment rather than shared key values.

The **collateral layer** captures credit facility security—A/R eligible for borrowing base, inventory, equipment, and real estate—with values sourced from A/R aging reports, borrowing base certificates, and prior memos.

The **relationship and policy layer** captures credit structure—facility type, amount, maturity, covenants, prior exceptions, and relationship history—derived primarily from prior credit memos and borrower applications.


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