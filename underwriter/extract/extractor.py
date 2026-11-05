"""Classify uploaded documents and extract them into the Deal schema with Claude."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from ..schema import BusinessProfile, CREData, Deal, DealTerms, DocumentRecord, FinancialStatements
from . import prompts
from .llm import ClaudeExtractor, DocInput
from .pdf_utils import inspect_pdf

FS_TYPES = {"financial_statements", "tax_return", "interim_financials", "projections"}
CRE_TYPES = {"cre_projections", "rent_roll", "appraisal", "budget", "loi"}


class DocClass(BaseModel):
    doc_index: int = Field(description="1-based index of the document as listed")
    doc_type: Literal["financial_statements", "tax_return", "interim_financials", "projections", "cre_projections",
                      "business_plan", "debt_schedule", "rent_roll", "appraisal", "budget", "loi", "bank_statements",
                      "personal_financial_statement", "investment_summary", "credit_guidelines", "other"]
    periods: list[str] = Field(default_factory=list)
    entity: Optional[str] = None
    summary: str = ""
    confidence: float = 0.9


class Classification(BaseModel):
    deal_type: Literal["small_business", "cre"]
    deal_type_rationale: str = ""
    documents: list[DocClass] = Field(default_factory=list)


class RequestHints(BaseModel):
    requested_amount: Optional[float] = None
    purpose: Optional[str] = None
    total_project_cost: Optional[float] = None
    equity_injection: Optional[float] = None
    collateral_offered: Optional[str] = None
    guarantors: list[str] = Field(default_factory=list)


def run_extraction(files: list[tuple[str, bytes]], deal_id: str, client=None,
                   progress: Callable[[str], None] = lambda s: None) -> Deal:
    docs, records, log = [], [], []
    for name, data in files:
        info = inspect_pdf(name, data)
        if info.error:
            raise ValueError(f"{name}: {info.error}")
        docs.append(DocInput(name, data))
        records.append(DocumentRecord(name=name, doc_type="unclassified", pages=info.pages, text_layer=info.has_text_layer))
        log.append(f"{name}: {info.pages} pages, {'text layer' if info.has_text_layer else 'image-only (scanned)'}")
    ex = ClaudeExtractor(client=client)
    progress("Classifying documents")
    cls = ex.extract(docs, prompts.SYSTEM, prompts.CLASSIFY, Classification, "classify", max_tokens=8000)
    for c in cls.documents:
        if 1 <= c.doc_index <= len(records):
            records[c.doc_index - 1].doc_type = c.doc_type
            records[c.doc_index - 1].classification_confidence = c.confidence
    log.append(f"deal type: {cls.deal_type} ({cls.deal_type_rationale})")

    fs_docs = [(i, d) for i, d in enumerate(docs) if records[i].doc_type in FS_TYPES | {"debt_schedule"}]
    cre_docs = [d for i, d in enumerate(docs) if records[i].doc_type in CRE_TYPES | {"business_plan", "investment_summary"}]

    def fs_job(item):
        i, d = item
        progress(f"Extracting financial statements: {d.name}")
        fs = ex.extract([d], prompts.SYSTEM, prompts.EXTRACT_FS, FinancialStatements, f"fs:{d.name}")
        fs.doc = d.name
        for li in fs.line_items:
            li.doc = li.doc or d.name
        for db in fs.debts:
            db.doc = db.doc or d.name
        return fs

    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_fs = [pool.submit(fs_job, it) for it in fs_docs] if cls.deal_type == "small_business" or fs_docs else []
        progress("Extracting business profile and NAICS")
        fut_profile = pool.submit(ex.extract, docs, prompts.SYSTEM, prompts.EXTRACT_PROFILE, BusinessProfile, "profile", 16000)
        fut_hints = pool.submit(ex.extract, docs, prompts.SYSTEM,
                                "Extract the loan request details stated in the documents (requested amount, purpose, total "
                                "project cost, equity injection, collateral offered, proposed guarantors).", RequestHints, "request", 4000)
        fut_cre = pool.submit(ex.extract, cre_docs or docs, prompts.SYSTEM, prompts.EXTRACT_CRE, CREData, "cre") if cls.deal_type == "cre" else None
        financials = [f.result() for f in fut_fs]
        profile = fut_profile.result()
        hints = fut_hints.result()
        cre = fut_cre.result() if fut_cre else None

    terms = DealTerms(deal_type=cls.deal_type, product="construction_mini_perm" if cls.deal_type == "cre" else "small_business_term",
                      borrower_name=profile.legal_name, borrower_address=profile.address, purpose=hints.purpose,
                      guarantors=hints.guarantors)
    if hints.requested_amount:
        from ..schema import LoanTerms
        terms.proposed_loan = LoanTerms(amount=hints.requested_amount, rate=0.085 if cls.deal_type == "cre" else 0.09,
                                        amort_months=300 if cls.deal_type == "cre" else 60)
        log.append("Proposed loan prefilled from the request; RATE AND AMORTIZATION ARE PLACEHOLDERS for the loan officer to set.")
    log += ex.usage.log
    return Deal(id=deal_id, terms=terms, profile=profile, financials=financials, cre=cre, documents=records,
                extraction_mode="llm", extraction_log=log)
