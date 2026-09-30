"""Tool-owned evidence metadata. Models never create source URLs or hashes."""
import hashlib
import ipaddress
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
import httpx
from . import config
from .schemas import Evidence, ImportedEvidence, QuestionSpec, utcnow


def public_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def normalize_import(items: list[ImportedEvidence], question: QuestionSpec) -> list[Evidence]:
    if len(items) > 20:
        raise ValueError("每个证据包最多 20 条")
    seen = set()
    out = []
    for i, item in enumerate(items, 1):
        if item.id and item.id in seen:
            raise ValueError(f"重复证据编号：{item.id}")
        if item.id:
            seen.add(item.id)
        if item.source_url and not public_url(str(item.source_url)):
            raise ValueError(f"来源地址不是公开 HTTP(S) URL：{item.id}")
        if item.published_at and item.published_at > question.as_of:
            raise ValueError(f"证据晚于信息截至时间：{item.id}")
        if item.updated_at and item.updated_at > question.as_of:
            raise ValueError(f"证据更新晚于信息截至时间：{item.id}")
        retrieved_at = item.retrieved_at or utcnow()
        if item.source_type != "exercise" and retrieved_at > question.as_of and (utcnow() - question.as_of).days > 1:
            raise ValueError(f"历史问题需要截点前冻结的证据快照：{item.id}")
        out.append(Evidence(
            id=f"E{i:03}", source_url=item.source_url, file_id=item.file_id,
            title=item.title, publisher=item.publisher, published_at=item.published_at,
            updated_at=item.updated_at, retrieved_at=retrieved_at, event_at=item.event_at,
            excerpt=item.excerpt, claim=item.claim, snapshot_path=item.snapshot_path,
            content_hash=hashlib.sha256(item.excerpt.encode()).hexdigest(),
            source_type=item.source_type,
            source_group=item.source_group or (urlparse(str(item.source_url)).hostname if item.source_url else item.file_id or "local"),
            date_status=item.date_status if item.source_type == "exercise" or item.snapshot_path else "unknown",
        ))
    return out


def online_search(question: QuestionSpec, data_dir: Path, queries: list[str] | None = None) -> list[Evidence]:
    if not config.TAVILY_API_KEY:
        raise ValueError("在线检索需要 TAVILY_API_KEY；可改用导入证据包。")
    if (utcnow() - question.as_of).days > 1:
        raise ValueError("历史问题不能用今天的网页作为截点前证据，请导入冻结证据包。")
    queries = list(dict.fromkeys(q[:400] for q in (queries or [question.question])[:3] if q.strip()))
    if not queries:
        queries = [question.question[:400]]

    def search_one(query: str) -> list[dict]:
        with httpx.Client(timeout=25) as client:
            response = client.post("https://api.tavily.com/search", json={
                "api_key": config.TAVILY_API_KEY, "query": query,
                "search_depth": "basic", "max_results": 8,
                "include_raw_content": "text", "include_answer": False,
            })
            response.raise_for_status()
            return [{**item, "query": query} for item in response.json().get("results", [])]

    results = []
    failures = []
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(search_one, query) for query in queries]
        # Read futures in query order so evidence IDs and duplicate selection stay stable.
        for index, future in enumerate(futures, 1):
            try:
                results.extend(future.result())
            except Exception as exc:
                detail = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                failures.append(f"第 {index} 条：{detail}")
    if len(failures) == len(queries):
        raise RuntimeError(f"Tavily 在线检索全部失败（{'；'.join(failures)}）")
    evidence = []
    seen = set()
    snapshot_dir = data_dir / "sources"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        url = result.get("url", "")
        if not public_url(url) or url in seen:
            continue
        content = (result.get("raw_content") or result.get("content") or "").strip()[:12000]
        if not content:
            continue
        seen.add(url)
        digest = hashlib.sha256(content.encode()).hexdigest()
        retrieved_at = utcnow()
        path = snapshot_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:12]}-{digest}.json"
        path.write_text(json.dumps({"provider": "tavily", "query": result.get("query"), "url": url, "title": result.get("title"), "content": content, "retrieved_at": retrieved_at.isoformat()}, ensure_ascii=False), encoding="utf-8")
        evidence.append(Evidence(
            id=f"E{len(evidence)+1:03}", source_url=url, title=result.get("title") or url,
            publisher=urlparse(url).hostname, retrieved_at=retrieved_at, excerpt=content,
            claim="待核查", snapshot_path=str(path.relative_to(data_dir)), content_hash=digest,
            source_type="secondary" if result.get("raw_content") else "snippet_only",
            source_group=urlparse(url).hostname or "unknown", date_status="unknown",
        ))
        if len(evidence) >= 10:
            break
    return evidence



def import_evidence(items, question: QuestionSpec, data_dir: Path):
    """Save new imports, never trust a client-supplied old path or timestamp."""
    from .provenance import save_snapshot, split_passages, select_passages
    from .schemas import RetrievalResult
    if len(items) > 20:
        raise ValueError("每个证据包最多20条")
    seen_ids = set()
    evidence, exclusions = [], []
    now = utcnow()
    historical = (now - question.as_of).total_seconds() > 86400
    for item in items:
        if item.id and item.id in seen_ids:
            raise ValueError("重复导入证据编号")
        if item.id:
            seen_ids.add(item.id)
        reason = None
        if item.source_url and not public_url(str(item.source_url)):
            reason = "来源地址不是公开HTTP(S) URL"
        elif (item.published_at and item.published_at > question.as_of) or (item.updated_at and item.updated_at > question.as_of):
            reason = "来源发布或更新晚于信息截至时间"
        elif historical and item.source_type != "exercise":
            reason = "客户端声明不能证明截点前冻结；请使用明确标注回看风险的历史练习"
        if reason:
            exclusions.append({"source": str(item.source_url or item.file_id), "reason": reason})
            continue
        safe = item.model_copy(update={"retrieved_at": now, "snapshot_path": None, "date_status": "unknown"})
        e = normalize_import([safe], question)[0]
        e.id = f"E{len(evidence)+1:03}"
        snapshot = save_snapshot(item.body or item.excerpt, {"provider": "import",
            "source_url": str(item.source_url) if item.source_url else None, "file_id": item.file_id,
            "title": item.title, "declared_snapshot_path": item.snapshot_path,
            "declared_retrieved_at": item.retrieved_at.isoformat() if item.retrieved_at else None}, data_dir)
        e.snapshot_path, e.snapshot_hash = snapshot.snapshot_path, snapshot.snapshot_hash
        e.content_truncated = snapshot.content_truncated
        e.content_kind = "body" if item.body else "imported_excerpt"
        e.source_kind = item.source_kind if item.source_kind_basis else "unknown"
        e.source_kind_basis = "导入者声明（未独立核实）：" + item.source_kind_basis if item.source_kind_basis else ""
        e.source_group = item.source_group or "document:" + hashlib.sha256(str(item.source_url or item.file_id).encode()).hexdigest()[:16]
        e.source_group_basis = ("导入者声明：" + (item.source_group_basis or "未提供分组依据")) if item.source_group else "单独资料，未核实独立性"
        e.availability = "historical_exercise" if historical else "unverified"
        e.event_status = "planned" if item.event_at and item.event_at > question.as_of else item.event_status
        e.date_basis = {"retrieved_at": "本次实际导入时间"}
        for field in ("published_at", "updated_at", "event_at"):
            if getattr(item, field):
                e.date_basis[field] = "导入者提供，未独立核实"
        e.passages = select_passages(split_passages(snapshot), [question.question])
        evidence.append(e)
    return RetrievalResult(evidence=evidence, exclusions=exclusions, status="partial" if exclusions else "completed")
