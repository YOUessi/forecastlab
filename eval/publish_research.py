"""Publish a reviewed supplement, preserving raw responses and recording every editorial correction.

The candidate generator cannot publish. A human/agent source audit must first set
quality_status=reviewed in report.json and record the review in quality_review.
"""
from __future__ import annotations
import argparse
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from app import config


def public_report(report):
    if report.get("quality_status") != "reviewed" or not report.get("quality_review"):
        raise ValueError("research candidate has not passed source review")
    calls = {call["request_id"]: call for call in report["calls"]}
    sources = {source["id"] for source in report["sources"]}
    for part in report["parts"]:
        call = calls.get(part.get("request_id"))
        if not call or call.get("finish_reason") != "stop":
            raise ValueError("section lacks a complete original model response")
        paragraphs = [p.strip() for section in part["sections"] for p in section["paragraphs"]]
        original = [p.strip() for p in call.get("raw_response", "").split("\n\n") if p.strip()]
        reviewed = list(original)
        seen = set()
        for edit in report["quality_review"].get("edits", []):
            if edit.get("request_id") != part["request_id"]:
                continue
            index = edit.get("paragraph_index")
            if (not isinstance(index, int) or index < 0 or index >= len(original)
                    or index in seen or edit.get("original") != original[index]
                    or not edit.get("reason") or not isinstance(edit.get("revised"), str)):
                raise ValueError("invalid or untraceable editorial correction")
            seen.add(index)
            reviewed[index] = edit["revised"]
        if paragraphs != reviewed:
            raise ValueError("section differs from the original model response without an audited correction")
        if any(set(section["source_ids"]) - sources for section in part["sections"]):
            raise ValueError("section cites an unknown source")
    public = {key: report[key] for key in ("run_id", "model", "generated_at", "parts", "quality_status", "quality_review")}
    fields = {"id", "title", "source_url", "published_at", "retrieved_at", "content_kind", "snapshot_hash"}
    public["sources"] = [{key: value for key, value in source.items() if key in fields} for source in report["sources"]]
    call_fields = {"request_id", "section", "model", "prompt_version", "enable_thinking", "started_at",
                   "input_hash", "status", "raw_response", "usage", "finish_reason", "reasoning_chars", "elapsed_seconds"}
    public["calls"] = [{key: value for key, value in call.items() if key in call_fields} for call in report["calls"]]
    return public


def render(report):
    report = public_report(report)
    sections = []
    for part in report["parts"]:
        for section in part["sections"]:
            paragraphs = "".join("<p>" + escape(p) + "</p>" for p in section["paragraphs"])
            sections.append("<section><small>" + escape(part["name"]) + "</small><h2>" + escape(section["title"]) +
                            "</h2>" + paragraphs + "<small>依据 " + escape(" · ".join(section["source_ids"])) + "</small></section>")
    sources = []
    for source in report["sources"]:
        url = source["source_url"]
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("invalid source URL")
        sources.append('<li><a href="' + escape(url, quote=True) + '">' + escape(source["id"] + " · " + source["title"]) +
                       '</a><small> · ' + escape(source["content_kind"]) + ' · 发布日期 ' + escape(source.get("published_at") or "未知") + '</small></li>')
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI与数学及科学科研 · 2027条件情景</title><style>body{margin:0;background:#f5f6ef;color:#18382f;font:17px/1.85 system-ui,sans-serif}main{max-width:860px;margin:48px auto;padding:0 28px 80px}header{border-bottom:2px solid #537967;padding-bottom:24px}h1{font:500 32px/1.4 Georgia,serif}h2{font-size:23px;line-height:1.5}section{margin:36px 0;border-top:1px solid #c9d5c9;padding-top:24px}p{margin:12px 0;overflow-wrap:anywhere}small{color:#66796b;font-size:13px}a{color:#32674e;overflow-wrap:anywhere}li{margin:14px 0}nav{display:flex;gap:24px;flex-wrap:wrap}@media(max-width:600px){main{margin:24px auto;padding:0 20px 50px}h1{font-size:25px}h2{font-size:20px}}</style><main><header><small>ForecastLab / 服务器模型专题</small><h1>AI发展将如何影响数学与科学科研？</h1><p>信息截止：2026-10-07 · 条件推演至2027年底 · 不分配二元概率</p><p>正文基于服务器 Qwen3-8B 响应，已核对来源归属、数量口径和情景边界。事实校订逐项记载于调用审计，原始响应完整保留；审查不等于独立复现实验或数学证明。资料在截点后取得；发布日期未知的材料不能证明其在截点前可用。本专题不是盲回测。</p><nav><a href="/">返回研究工作台</a>""" + '<a href="research-' + escape(report["run_id"], quote=True) + '.json">来源与调用审计</a></nav></header>' + "".join(sections) + '<h2>来源与取证</h2><ol>' + "".join(sources) + '</ol></main></html>'


def publish(run_id):
    root = config.DATA_DIR / "research-supplement" / run_id
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    public = public_report(report)
    doc = render(report)
    (root / "report.html").write_text(doc, encoding="utf-8")
    destination = config.ROOT / "frontend/dist/assets"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"research-{run_id}.html").write_text(doc, encoding="utf-8")
    target = destination / f"research-{run_id}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"run_[a-zA-Z0-9_-]+", args.run_id):
        parser.error("invalid run ID")
    publish(args.run_id)
