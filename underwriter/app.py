"""FastAPI backend + static review UI.

Run:  uvicorn underwriter.app:app --reload   (then open http://localhost:8000)

Storage (gitignored): data/deals/<id>.json, data/uploads/<id>/*.pdf. Uploaded PDFs are deleted after
UNDERWRITER_RETENTION_HOURS (default 24). Nothing borrower-specific is logged.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from .env import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .engine.common import jsonable
from .extract.llm import DEFAULT_MODEL, LLMUnavailable, api_available
from .memo.docx_export import render_docx
from .pipeline import analyze
from .schema import Deal

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("UNDERWRITER_DATA_DIR", ROOT / "data"))
DEALS = DATA / "deals"
UPLOADS = DATA / "uploads"
FIXTURES = ROOT / "samples" / "fixtures"
RETENTION_H = float(os.environ.get("UNDERWRITER_RETENTION_HOURS", "24"))
for d in (DEALS, UPLOADS):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("underwriter")
app = FastAPI(title="Invest Detroit AI Underwriting Assistant")
JOBS: dict[str, dict] = {}
SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _safe_id(x: str) -> str:
    if not SAFE.match(x or ""):
        raise HTTPException(400, "invalid id")
    return x


def _deal_path(deal_id: str) -> Path:
    return DEALS / f"{_safe_id(deal_id)}.json"


def load_deal(deal_id: str) -> Deal:
    p = _deal_path(deal_id)
    if not p.exists():
        raise HTTPException(404, "deal not found")
    return Deal.model_validate_json(p.read_text())


def save_deal(deal: Deal) -> None:
    _deal_path(deal.id).write_text(deal.model_dump_json(indent=1))


def result_json(deal: Deal) -> dict:
    out = analyze(deal)
    return jsonable(out)


def purge_old_uploads() -> None:
    cutoff = time.time() - RETENTION_H * 3600
    for d in UPLOADS.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


@app.get("/api/status")
def status():
    purge_old_uploads()
    fixtures = sorted(p.stem for p in FIXTURES.glob("*.json")) if FIXTURES.exists() else []
    return {"llm_available": api_available(), "model": DEFAULT_MODEL, "fixtures": fixtures,
            "retention_hours": RETENTION_H}


@app.get("/api/deals")
def list_deals():
    out = []
    for p in sorted(DEALS.glob("*.json"), key=lambda x: -x.stat().st_mtime):
        try:
            d = json.loads(p.read_text())
            out.append({"id": d["id"], "borrower": d["terms"].get("borrower_name"), "deal_type": d["terms"]["deal_type"],
                        "mode": d.get("extraction_mode"), "updated": p.stat().st_mtime})
        except Exception:  # noqa: BLE001
            continue
    return out


@app.post("/api/deals/fixture/{name}")
def load_fixture(name: str):
    p = FIXTURES / f"{_safe_id(name)}.json"
    if not p.exists():
        raise HTTPException(404, "fixture not found")
    deal = Deal.model_validate_json(p.read_text())
    deal.id = f"{name}-{uuid.uuid4().hex[:6]}"
    save_deal(deal)
    return {"id": deal.id}


@app.post("/api/deals/upload")
async def upload(files: list[UploadFile] = File(...)):
    if not api_available():
        raise HTTPException(400, "No ANTHROPIC_API_KEY configured on the server. Add it to .env, or load a sample deal.")
    deal_id = f"deal-{uuid.uuid4().hex[:8]}"
    folder = UPLOADS / deal_id
    folder.mkdir(parents=True)
    payload = []
    for f in files:
        name = Path(f.filename or "upload.pdf").name
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, f"{name}: only PDF files are accepted")
        data = await f.read()
        (folder / name).write_bytes(data)
        payload.append((name, data))
    job = {"id": deal_id, "status": "running", "progress": ["Upload received"], "error": None}
    JOBS[deal_id] = job

    def work():
        from .extract.extractor import run_extraction
        try:
            deal = run_extraction(payload, deal_id, progress=lambda s: job["progress"].append(s))
            save_deal(deal)
            job["progress"].append("Computing analysis and drafting Investment Summary")
            analyze(deal)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("extraction failed for %s", deal_id)
            job["status"] = "error"
            job["error"] = str(e)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": deal_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = JOBS.get(_safe_id(job_id))
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str):
    deal = load_deal(deal_id)
    try:
        res = result_json(deal)
    except Exception as e:  # noqa: BLE001
        log.exception("analysis failed")
        return JSONResponse({"deal": json.loads(deal.model_dump_json()), "result": None, "error": str(e)})
    return {"deal": json.loads(deal.model_dump_json()), "result": res}


@app.put("/api/deals/{deal_id}")
def update_deal(deal_id: str, body: dict):
    _ = load_deal(deal_id)
    body["id"] = deal_id
    try:
        deal = Deal.model_validate(body)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Invalid deal data: {e}") from e
    save_deal(deal)
    return get_deal(deal_id)


@app.delete("/api/deals/{deal_id}")
def delete_deal(deal_id: str):
    _deal_path(deal_id).unlink(missing_ok=True)
    shutil.rmtree(UPLOADS / _safe_id(deal_id), ignore_errors=True)
    return {"ok": True}


@app.get("/api/deals/{deal_id}/export.docx")
def export_docx(deal_id: str):
    deal = load_deal(deal_id)
    res = analyze(deal)
    data = render_docx(res["memo"], deal.terms.borrower_name or "")
    fname = re.sub(r"[^A-Za-z0-9]+", "_", deal.terms.borrower_name or deal.id).strip("_") + "_Investment_Summary_DRAFT.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/deals/{deal_id}/export.json")
def export_json(deal_id: str):
    deal = load_deal(deal_id)
    return Response(deal.model_dump_json(indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{deal.id}.json"'})


def _find_pdf(deal_id: str, doc: str) -> Path | None:
    name = Path(doc).name
    for base in (UPLOADS / _safe_id(deal_id), ROOT / "samples" / "inputs"):
        p = base / name
        if p.exists() and p.suffix.lower() == ".pdf":
            return p
    return None


@app.get("/api/deals/{deal_id}/page")
def page_image(deal_id: str, doc: str, page: int = 1):
    p = _find_pdf(deal_id, doc)
    if p is None:
        raise HTTPException(404, "source document not available (uploads are deleted after the retention period)")
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(p))
    if not 1 <= page <= len(pdf):
        raise HTTPException(404, "page out of range")
    img = pdf[page - 1].render(scale=1.6).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
