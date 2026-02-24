# Care Plan Generator — Design Document

**Client:** CVS Specialty Pharmacy  
**Version:** 0.1 (Draft)  
**Date:** 2026-02-23

---

## 1. Background & Objectives

### Business Context

CVS Specialty Pharmacy needs to generate a Care Plan for each patient for Medicare reimbursement and Pharma compliance reporting. Currently completed manually by pharmacists, each plan takes 20–40 minutes, and a significant backlog has built up due to severe staffing shortages.

### Project Goals

Build a web form tool that allows Medical Assistants to quickly enter patient and order information, have an LLM automatically generate a standardized Care Plan, and support report export.

### Users

- **Primary Users:** CVS healthcare workers (Medical Assistants, Pharmacists)
- **Non-Users:** Patients do not interact with this system
- **Care Plan Distribution:** After the system generates a Care Plan, staff print it and hand it to the patient

---

## 2. Core Concepts

| Concept           | Description                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------- |
| **Order**         | One medication corresponds to one order, which corresponds to one Care Plan                         |
| **Care Plan**     | Generated for a single order; includes: Problem List, Goals, Pharmacist Interventions, Monitoring Plan |
| **Provider**      | The prescribing physician, uniquely identified by NPI (10-digit unique code); only entered once in the system |
| **MRN**           | Patient unique ID, 6-digit number                                                                   |

---

## 3. Input Data Specifications

### 3.1 Form Fields

| Field                     | Type           | Validation Rules                  |
| ------------------------- | -------------- | --------------------------------- |
| Patient First Name        | string         | Required, non-empty               |
| Patient Last Name         | string         | Required, non-empty               |
| Patient MRN               | string         | Required, unique 6-digit number   |
| Patient Date of Birth     | date           | Required (used for duplicate detection) |
| Patient Primary Diagnosis | string         | Required, ICD-10 format           |
| Additional Diagnoses      | list\<string\> | Optional, each must be valid ICD-10 |
| Medication Name           | string         | Required, non-empty               |
| Medication History        | list\<string\> | Optional                          |
| Referring Provider        | string         | Required, non-empty               |
| Referring Provider NPI    | string         | Required, 10-digit numeric        |
| Patient Records           | string or PDF  | Optional, for LLM reference       |

### 3.2 Data Integrity Rules

- ICD-10 format validation (regex or standard code library)
- NPI format validation (10-digit numeric; optionally integrate NPI Registry API for real-world verification)
- MRN uniqueness constraint (enforced at the database level)
- Provider entered once and reused; NPI is the unique key

---

## 4. Duplicate Detection Rules

### 4.1 Order Duplicate Detection

| Scenario                                      | Handling                              | Reason                        |
| --------------------------------------------- | ------------------------------------- | ----------------------------- |
| Same patient + same medication + **same day** | ❌ **ERROR** — Block submission       | Definitely a duplicate submission |
| Same patient + same medication + **different day** | ⚠️ **WARNING** — Allow after confirmation | Likely a refill           |

### 4.2 Patient Duplicate Detection

| Scenario                             | Handling                              | Reason                    |
| ------------------------------------ | ------------------------------------- | ------------------------- |
| Same MRN + different name or DOB     | ⚠️ **WARNING** — Allow after confirmation | Possible data entry error |
| Same name + same DOB + different MRN | ⚠️ **WARNING** — Allow after confirmation | Possibly the same person  |

### 4.3 Provider Duplicate Detection

| Scenario                              | Handling                              | Reason                        |
| ------------------------------------- | ------------------------------------- | ----------------------------- |
| Same NPI + different Provider name    | ❌ **ERROR** — Must be corrected before proceeding | NPI is a unique identifier |

### 4.4 ERROR vs WARNING Behavior Definition

| Type    | UI Behavior                                         | Can Proceed?              |
| ------- | --------------------------------------------------- | ------------------------- |
| ERROR   | Blocking prompt appears; form cannot be submitted   | ❌ No, must be corrected  |
| WARNING | Confirmation dialog appears; user must confirm      | ✅ Yes, proceed after confirmation |

---

## 5. Care Plan Generation

### 5.1 Flow

```
User fills out form → Validation passes → LLM API called → Care Plan text returned → User downloads
```

### 5.2 Care Plan Output Content (Required)

1. **Problem List** — Based on diagnoses and medication history
2. **Goals** — Treatment objectives
3. **Pharmacist Interventions** — Pharmacist intervention measures
4. **Monitoring Plan** — Monitoring schedule

### 5.3 Output Format

- Format: Downloadable text file (`.txt` or `.pdf`, to be confirmed)
- Suggested filename: `{MRN}_{MedicationName}_{Date}.txt`

### 5.4 LLM Integration

- LLM Provider: TBD (OpenAI / Anthropic / Azure OpenAI, etc.)
- Input context: Patient information + diagnoses + medication history + uploaded Patient Records
- PHI (Protected Health Information) compliance must be considered; LLM calls must go through channels covered by a BAA (Business Associate Agreement)

---

## 6. Export & Reporting

- Supports batch export of order data for Pharma reporting
- Export format: TBD (CSV / Excel / PDF)
- Export scope: Filter by time period, medication, Provider, etc. — to be confirmed

---

## 7. Feature Priorities

| Feature                          | Priority    | Notes                                   |
| -------------------------------- | ----------- | --------------------------------------- |
| Patient/Order duplicate detection | P0 Must-Have | Must not disrupt existing workflows    |
| Care Plan generation & download  | P0 Must-Have | Core business value                    |
| Provider management & duplicate detection | P0 Must-Have | Affects Pharma reporting accuracy |
| Form data validation             | P0 Must-Have | Foundation for data quality            |
| Pharma report export             | P0 Must-Have | Compliance requirement                 |

---

## 8. Non-Functional Requirements

| Category          | Requirement                                                                              |
| ----------------- | ---------------------------------------------------------------------------------------- |
| **Security**      | Handles PHI; must comply with HIPAA; LLM calls must go through BAA-compliant channels   |
| **Error Handling**| Error messages must be clear and readable to users; no exposure of technical details     |
| **Testability**   | Core logic (validation, duplicate detection, LLM calls) must have automated test coverage |
| **Maintainability** | Code should be modular, well-structured, and easy to navigate                          |
| **Out-of-the-box** | Project must be runnable end-to-end locally, with README and environment configuration  |

---

## 9. Open Questions (Need Client Alignment)

### 9.1 Data & Validation

- Is DOB (date of birth) a required field? (The duplicate detection logic depends on it)
- Is ICD-10 validation format-only, or does it need to be verified against a standard code library?
- Does NPI need real-time validation via the NPI Registry API?
- Is "Medication Name" free text or selected from a drug database?

### 9.2 Care Plan Generation

- What is the Care Plan download format: `.txt`, `.pdf`, or both?
- Has the LLM provider been decided? Is there an existing HIPAA BAA in place?
- How should generation failures be handled (LLM timeout/error)? Is a retry mechanism needed?

### 9.3 Provider Management

- Does Provider need a dedicated management interface (CRUD)?
- When entering a new Provider, should the name be auto-filled from NPI Registry lookup, or entered manually?

### 9.4 Export Reports

- What is the export format? (CSV / Excel / PDF)
- What filter dimensions are needed? (Time period, medication, Provider, etc.)
- Should exports be scheduled/automatic, or only manually triggered?

### 9.5 System Integration

- Does this need to integrate with existing CVS systems (e.g., EMR, EHR), or run fully standalone?
- Do users need login authentication? Are role-based permissions needed (Medical Assistant vs. Pharmacist)?
- What is the maximum file size for Patient Records PDF uploads?

---

## 10. Recommended Tech Stack (To Be Confirmed)

| Layer    | Recommendation                          | Notes                                           |
| -------- | --------------------------------------- | ----------------------------------------------- |
| Frontend | React + TypeScript                      | Complex form interactions; component-based is easier to maintain |
| Backend  | Python (Django + Django REST Framework) | TBD                                             |
| Database | PostgreSQL                              | Relational; well-suited for integrity constraints |
| LLM      | OpenAI / Anthropic (BAA required)       | Client must confirm compliant channel           |
| Deployment | TBD (Cloud / On-premise / CVS intranet) | Affects HIPAA compliance approach             |

---

_This document is a draft. It will be updated after client alignment on the open questions listed in Section 9._
