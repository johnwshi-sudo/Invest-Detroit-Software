import json
from types import SimpleNamespace

import pytest

from underwriter.extract.llm import ClaudeExtractor, strict_json_schema
from underwriter.extract.pdf_utils import inspect_pdf
from underwriter.memo.docx_export import render_docx
from underwriter.naics import benchmarks as nb
from underwriter.pipeline import analyze
from underwriter.schema import BusinessProfile, CREData, FinancialStatements


def test_pipeline_end_to_end_and_docx(sb_deal, cre_deal):
    for deal in (sb_deal, cre_deal):
        out = analyze(deal)
        titles = [s["title"] for s in out["memo"]["sections"]]
        assert "Industry Benchmarking (NAICS)" in titles and "Credit Guideline Compliance" in titles
        assert render_docx(out["memo"])[:2] == b"PK"   # valid .docx (zip)
        json.dumps(out, default=lambda o: o.to_dict())


def test_memo_never_invents_missing_qualitative_facts(sb_deal):
    out = analyze(sb_deal)
    blocks = [b for s in out["memo"]["sections"] for b in s["blocks"]]
    assert any(b["type"] == "placeholder" for b in blocks)   # e.g. banking relationship not provided


def test_strict_schema_is_structured_output_friendly():
    for m in (FinancialStatements, BusinessProfile, CREData):
        s = strict_json_schema(m)

        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "object" and "properties" in n:
                    assert n["additionalProperties"] is False
                    assert set(n["required"]) == set(n["properties"])
                assert "default" not in n
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(s)


def test_pdf_intake_rejects_non_pdf():
    assert inspect_pdf("x.pdf", b"hello").error


class FakeStream:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return SimpleNamespace(stop_reason="end_turn", usage=None,
                               content=[SimpleNamespace(type="text", text=self.text)])


class FakeClient:
    """Returns canned JSON per request; records requests to check prompt structure."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append(kw)
        return FakeStream(self.responses.pop(0))


def test_extractor_validates_and_repairs():
    good = json.dumps({"legal_name": "Acme", "naics_suggestions": [{"code": "722511"}]})
    client = FakeClient(["{not json", good])
    ex = ClaudeExtractor(client=client)
    from underwriter.extract.llm import DocInput
    prof = ex.extract([DocInput("a.pdf", b"%PDF-1.4")], "sys", "extract", BusinessProfile, "profile")
    assert prof.legal_name == "Acme"
    req = client.requests[0]
    doc_blocks = [b for b in req["messages"][0]["content"] if b["type"] == "document"]
    assert doc_blocks and doc_blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"]["format"]["type"] == "json_schema"


def test_naics_validation_and_lookup():
    p = BusinessProfile(description="full service restaurant", naics_suggestions=[{"code": "999999"}])
    res = nb.identify(p)
    assert res["code"] == "722511" and any("not a valid" in f.message for f in res["flags"])
    assert nb.industry_for("423120")["label"].startswith("Motor vehicle and motor vehicle parts")
    assert nb.industry_for("531120")["label"].startswith("Lessors of buildings")


def test_run_extraction_orchestration_with_fake_claude(sb_deal):
    """Exercise classify -> per-document extraction -> Deal assembly -> analysis, routing fake responses by schema."""
    from underwriter.extract import extractor as X
    fs_json = sb_deal.financials[0].model_dump_json()
    responses = {
        "deal_type": json.dumps({"deal_type": "small_business", "deal_type_rationale": "operating business",
                                 "documents": [{"doc_index": 1, "doc_type": "financial_statements", "periods": ["FY2023"], "summary": "FS", "confidence": 0.95}]}),
        "line_items": fs_json,
        "legal_name": sb_deal.profile.model_dump_json(),
        "requested_amount": json.dumps({"requested_amount": 250000, "purpose": "equipment", "guarantors": ["Owner A"]}),
    }

    class RoutingClient(FakeClient):
        def _stream(self, **kw):
            props = kw["output_config"]["format"]["schema"]["properties"]
            key = next(k for k in responses if k in props)
            return FakeStream(responses[key])

    import io
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(612, 792)
    buf = io.BytesIO()
    w.write(buf)
    pdf = buf.getvalue()
    deal = X.run_extraction([("fs.pdf", pdf)], "t1", client=RoutingClient([]))
    assert deal.extraction_mode == "llm" and deal.documents[0].doc_type == "financial_statements"
    assert deal.terms.proposed_loan.amount == 250000
    assert any("PLACEHOLDERS" in l for l in deal.extraction_log)
    out = analyze(deal)
    assert out["summary"]["revenue"] == 2_200_000
