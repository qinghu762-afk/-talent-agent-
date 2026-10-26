"""Five LangGraph agents operating exclusively on core-authorized snapshots."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
from contextlib import asynccontextmanager
from typing import TypedDict

import httpx
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, field_validator, model_validator

from .ai_domain import (
    claim_is_positive,
    fact_count,
    ground_profile,
    merge_profiles,
    missing_core_fields,
    normalized,
    score_candidate,
)
from .prompts import model_prompt


def split_documents(text: str, *, chunk_size: int = 1200, chunk_overlap: int = 200) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                              add_start_index=True, separators=['\n\n', '\n', '。', '；', ' ', ''])
    return splitter.split_documents([Document(page_content=text)])


def current_hit(hit: dict, snapshot: dict, *, kind: str, org_id: str) -> bool:
    if str(hit.get('source_id')) != str(snapshot['id']):
        return False
    if hit.get('org_id') is not None and str(hit['org_id']) != str(org_id):
        return False
    if hit.get('kind', kind) != kind:
        return False
    if snapshot.get('revision') is not None:
        if hit.get('revision') != snapshot['revision'] or snapshot.get('indexed_revision') != snapshot['revision']:
            return False
    if snapshot.get('index_model') and hit.get('index_model') != snapshot['index_model']:
        return False
    if snapshot.get('permission_version') is not None and hit.get('permission_version') != snapshot['permission_version']:
        return False
    return True


class AIUnavailable(RuntimeError):
    """A required real external dependency was not configured or reachable."""


class Extraction(BaseModel):
    profile: dict

    @model_validator(mode='before')
    @classmethod
    def canonical_evidence_layout(cls, value):
        """Normalize equivalent JSON layouts; all facts still pass ground_profile.

        Small local models sometimes emit a sibling evidence list or group several
        values under one quote. Moving/splitting those claims adds no new fact or
        citation and lets each value be independently checked against the source.
        """
        if not isinstance(value, dict) or not isinstance(value.get('profile'), dict):
            return value
        profile = dict(value['profile'])
        inside, outside = profile.get('evidence', []), value.get('evidence', [])
        if not isinstance(inside, list) or not isinstance(outside, list):
            raise ValueError('Evidence must be a list')
        evidence = []
        for item in inside + outside:
            if isinstance(item, dict) and isinstance(item.get('field'), str):
                item = {**item, 'field': item['field'].strip().casefold()}
            if isinstance(item, dict) and isinstance(item.get('value'), list):
                evidence.extend({**item, 'value': piece} for piece in item['value'])
            else:
                evidence.append(item)
        if isinstance(profile.get('skills'), list):
            skills = []
            for item in profile['skills']:
                if isinstance(item, dict) and isinstance(item.get('value'), str) and isinstance(item.get('quote'), str):
                    skills.append(item['value'])
                    evidence.append({'field': 'skills', 'value': item['value'], 'quote': item['quote']})
                else:
                    skills.append(item)
            profile['skills'] = skills
        profile['evidence'] = evidence
        # An evidence item is also a candidate value. Some structured-output
        # models return only those items rather than duplicating profile fields.
        # Reconstruct the missing shape, then apply the identical grounding gate.
        for field in ('name', 'phone', 'email', 'location', 'skills', 'education', 'experiences', 'projects', 'certificates', 'intentions'):
            if profile.get(field):
                continue
            values = [item['value'] for item in evidence if isinstance(item, dict)
                      and item.get('field') == field and item.get('value') is not None]
            if not values:
                continue
            if field in {'name', 'phone', 'email', 'location'}:
                if any(value != values[0] for value in values):
                    raise ValueError('Conflicting evidence-only identity candidates')
                profile[field] = values[0]
            else:
                profile[field] = values
        return {**value, 'profile': profile}

    @field_validator('profile')
    @classmethod
    def validate_shape(cls, value):
        if any(value.get(field) is not None and not isinstance(value[field], str) for field in ('name', 'phone', 'email', 'location')):
            raise ValueError('Identity fields must be strings or null')
        for field in ('skills', 'education', 'experiences', 'projects', 'certificates', 'intentions', 'evidence'):
            if field in value and not isinstance(value[field], list):
                raise ValueError('Extraction list required: ' + field)
        if any(not isinstance(item, str) for item in value.get('skills', [])):
            raise ValueError('Skills must be strings')
        for item in value.get('evidence', []):
            if not isinstance(item, dict) or not isinstance(item.get('field'), str) or not isinstance(item.get('quote'), str) or 'value' not in item:
                raise ValueError('Evidence must bind field, value and original quote')
        return value


class Citation(BaseModel):
    source_id: str
    quote: str
    title: str = ""


class ChatAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class TrainingAnswer(BaseModel):
    title: str
    course_ids: list[str]
    reasons: dict[str, str] = Field(default_factory=dict)


class DifyGateway:
    """LangChain Runnable around a private Dify workflow; no model fallback."""

    def __init__(self):
        self.url = os.getenv("DIFY_API_URL", "").rstrip("/")
        self.key = os.getenv("DIFY_APP_KEY", "")
        self.runnable = RunnableLambda(self._invoke)

    async def _invoke(self, request: dict) -> dict:
        if not self.url or not self.key:
            raise AIUnavailable("DIFY_API_URL and DIFY_APP_KEY are required")
        instructions = model_prompt(request)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), follow_redirects=False) as client:
                workflow = os.getenv("DIFY_APP_MODE", "workflow") == "workflow"
                body = {"inputs": {"prompt": instructions} if workflow else {}, "response_mode": "blocking", "user": request.get("user", "platform")}
                if not workflow:
                    body["query"] = instructions
                response = await client.post(self.url + ("/workflows/run" if workflow else "/chat-messages"),
                                             headers={"Authorization": "Bearer " + self.key}, json=body)
                response.raise_for_status()
                data = response.json()
                if workflow:
                    if data.get("data", {}).get("status") != "succeeded":
                        raise AIUnavailable("Dify workflow did not succeed")
                    answer = data["data"]["outputs"]["text"]
                else:
                    answer = data["answer"]
                if isinstance(answer, dict):
                    return answer
                answer = answer.strip()
                if answer.startswith("```"):
                    answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer)
                parsed = json.loads(answer)
                if not isinstance(parsed, dict):
                    raise ValueError("Dify result must be a JSON object")
                return parsed
        except httpx.HTTPError as exc:
            raise AIUnavailable("Dify inference failed; no fallback result was produced") from exc
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError("Dify result has invalid structured output") from exc

    async def __call__(self, request: dict) -> dict:
        return await self.runnable.ainvoke(request)


class MilvusIndex:
    """Separate platform collection, permission/revision metadata and real embeddings."""

    def __init__(self):
        self.url = os.getenv("MILVUS_URL", "")
        self.embedding_url = os.getenv("OLLAMA_URL", "").rstrip("/")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "")
        self.collection = "talent_platform_documents_v2"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_url or not self.embedding_model:
            raise AIUnavailable("Embedding gateway and EMBEDDING_MODEL are required")
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(self.embedding_url + "/api/embed", json={"model": self.embedding_model, "input": texts})
            response.raise_for_status()
            return response.json()["embeddings"]

    def client(self):
        if not self.url:
            raise AIUnavailable("MILVUS_URL is required")
        from pymilvus import MilvusClient
        return MilvusClient(uri=self.url)

    async def upsert(self, document: dict, *, kind: str) -> dict:
        text = document.get("text") or json.dumps(document.get("profile", {}), ensure_ascii=False)
        chunks = [part.page_content for part in split_documents(text)]
        if not chunks:
            raise ValueError("Cannot index an empty document")
        embeddings = await self.embed(chunks)

        def write():
            client = self.client()
            try:
                if not client.has_collection(self.collection):
                    from pymilvus import DataType
                    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
                    schema.add_field('id', DataType.VARCHAR, is_primary=True, max_length=128)
                    schema.add_field('source_id', DataType.VARCHAR, max_length=128)
                    schema.add_field('vector', DataType.FLOAT_VECTOR, dim=len(embeddings[0]))
                    indexes = client.prepare_index_params()
                    indexes.add_index(field_name='vector', index_type='AUTOINDEX', metric_type='COSINE')
                    client.create_collection(self.collection, schema=schema, index_params=indexes)
                rows = []
                for index, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                    rows.append({"id": f'{kind}:{document["id"]}:{document.get("revision", 1)}:{index}', "vector": vector,
                                 "source_id": str(document["id"]), "source_path": f'{kind}/{document["id"]}', "chunk": index,
                                 "text": chunk, "kind": kind, "org_id": str(document["org_id"]),
                                 "scope": document.get("scope", "org"), "owner_id": str(document.get("owner_id", "")),
                                 "revision": document.get("revision", 1), "permission_version": document.get("permission_version", 1),
                                 "index_model": self.embedding_model})
                client.upsert(self.collection, rows)
                # A shorter document at the same revision can leave tail chunks, while old
                # revisions can crowd current hits out of the recall window. Prune only after
                # the replacement has been written successfully, under the same tenant scope.
                source_scope = f"source_id == {json.dumps(str(document['id']))} and org_id == {json.dumps(str(document['org_id']))} and kind == {json.dumps(kind)}"
                current_revision = int(document.get("revision", 1))
                client.delete(self.collection, filter=source_scope + f" and (revision < {current_revision} or (revision == {current_revision} and chunk >= {len(rows)}))")
                return {"indexed_revision": document.get("revision", 1), "index_model": self.embedding_model, "chunks": len(rows)}
            finally:
                client.close()
        return await asyncio.to_thread(write)

    async def search(self, query: str, *, allowed_ids: list[str], org_id: str, kind: str, limit: int = 100) -> list[dict]:
        if not allowed_ids:
            return []
        vectors = await self.embed([query])
        # Values are JSON literals, never executable Milvus expression fragments.
        expression = f"source_id in {json.dumps(allowed_ids)} and org_id == {json.dumps(str(org_id))} and kind == {json.dumps(kind)}"

        def search():
            client = self.client()
            try:
                grouping = {'group_by_field': 'source_id', 'group_size': 3, 'strict_group_size': False} if kind == 'talent' else {}
                found = client.search(self.collection, data=vectors, limit=min(limit, 100), filter=expression,
                                      output_fields=["source_id", "source_path", "chunk", "text", "kind", "revision", "index_model", "org_id", "scope", "owner_id", "permission_version"], **grouping)
                return [{**hit["entity"], "semantic_score": float(hit.get("distance", 0))} for hit in found[0]]
            finally:
                client.close()
        return await asyncio.to_thread(search)

    async def delete(self, *, source_id: str, org_id: str, kind: str) -> dict:
        expression = f"source_id == {json.dumps(str(source_id))} and org_id == {json.dumps(str(org_id))} and kind == {json.dumps(kind)}"
        def remove():
            client = self.client()
            try:
                if client.has_collection(self.collection):
                    client.delete(self.collection, filter=expression)
                return {"deleted": True, "source_id": str(source_id)}
            finally:
                client.close()
        return await asyncio.to_thread(remove)


class AgentState(TypedDict, total=False):
    kind: str
    payload: dict
    actor: dict
    result: dict
    rounds: int
    issues: list[str]
    profile: dict
    round_issues: list[str]
    gained_facts: int
    valid_round: bool
    retry_resume: bool
    execution_summary: list[dict]
    versions: dict


class AIPlatform:
    def __init__(self, *, model=None, vectors=None, checkpointer=None, analysis=None):
        self.model = model or DifyGateway()
        self.vectors = vectors or MilvusIndex()
        self.checkpointer = checkpointer
        self.analysis = analysis
        self._inference_lock = asyncio.Lock()

    async def ask(self, request: dict, actor: dict) -> dict:
        request = {**request, "user": str(actor.get("id", "platform")), "response_format": "json_object"}
        async with self._inference_lock:
            result = self.model(request)
            return await result if inspect.isawaitable(result) else result

    def graph(self, saver):
        builder = StateGraph(AgentState)
        builder.add_node("approval", self._approval)
        builder.add_node("talent_agent", self._talent)
        builder.add_node("resume_extract", self._resume_extract)
        builder.add_node("resume_validate", self._resume_validate)
        builder.add_node("matching_agent", self._matching)
        builder.add_node("knowledge_agent", self._knowledge)
        builder.add_node("development_agent", self._development)
        builder.add_node("analytics_agent", self._analytics)
        builder.add_edge(START, "approval")
        routes = {"resume": "resume_extract", "job": "talent_agent", "index": "talent_agent", "delete_index": "talent_agent",
                  "duplicates": "talent_agent", "match": "matching_agent", "search": "matching_agent",
                  "knowledge": "knowledge_agent", "chat": "knowledge_agent", "assessment": "development_agent",
                  "training": "development_agent", "analysis": "analytics_agent"}
        builder.add_conditional_edges("approval", lambda state: routes[state["kind"]])
        builder.add_edge("talent_agent", END)
        builder.add_edge("resume_extract", "resume_validate")
        builder.add_conditional_edges("resume_validate", lambda state: "resume_extract" if state.get("retry_resume") else END)
        for node in ("matching_agent", "knowledge_agent", "development_agent", "analytics_agent"):
            builder.add_edge(node, END)
        return builder.compile(checkpointer=saver)

    @asynccontextmanager
    async def _saver(self):
        if self.checkpointer is not None:
            yield self.checkpointer
            return
        dsn = os.getenv("CHECKPOINT_DATABASE_URL", "")
        if not dsn:
            raise AIUnavailable("CHECKPOINT_DATABASE_URL is required; production cannot use in-memory checkpoints")
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            await saver.setup()
            yield saver

    async def execute(self, kind: str, payload: dict, *, run_id: str, actor: dict) -> dict:
        if kind not in {"resume", "job", "index", "delete_index", "duplicates", "search", "match", "knowledge", "chat", "assessment", "training", "analysis"}:
            raise ValueError("Unsupported AI operation")
        if not actor.get("id") or not actor.get("org_id"):
            raise ValueError("Authenticated actor snapshot is required")
        # Bind checkpoint identity to tenant, actor, operation and run.
        thread_id = hashlib.sha256(f'{actor["org_id"]}:{actor["id"]}:{kind}:{run_id}'.encode()).hexdigest()
        async with self._saver() as saver:
            graph = self.graph(saver)
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 20}
            if "approval_decision" in payload:
                state = await graph.aget_state(config)
                if not state.next:
                    raise ValueError("No pending approval for this actor and run")
                incoming = Command(resume={"approved": payload["approval_decision"] is True})
            else:
                saved = await graph.aget_state(config)
                same_input = saved.values and saved.values.get('payload') == payload and saved.values.get('actor') == actor
                if same_input and not saved.next:
                    return {**saved.values.get('result', {}), 'versions': saved.values.get('versions', {})}
                incoming = None if same_input else {"kind": kind, "payload": payload, "actor": actor, "rounds": 0, "issues": [],
                            "profile": {}, "result": {}, "round_issues": [], "retry_resume": False, "gained_facts": 0, 'execution_summary': [], 'versions': self.versions()}
            final = await graph.ainvoke(incoming, config=config)
            if final.get("__interrupt__"):
                return {"status": "awaiting_approval", "approval": final["__interrupt__"][0].value, "run_id": run_id}
            return {**final["result"], 'versions': final.get('versions', {})}

    async def _approval(self, state: AgentState) -> dict:
        if state["payload"].get("approval_required"):
            decision = interrupt({"kind": state["kind"], "reason": "业务审批后继续执行"})
            if not decision.get("approved"):
                raise ValueError("AI execution approval rejected")
        return {}

    async def _talent(self, state: AgentState) -> dict:
        payload, actor, kind = state["payload"], state["actor"], state["kind"]
        if kind == "delete_index":
            index_kind = payload.get("kind")
            if index_kind not in {"talent", "knowledge"}:
                raise ValueError("Unsupported index deletion kind")
            org_id = str(payload.get('org_id', actor['org_id']))
            if org_id != str(actor['org_id']) and actor.get('role') != 'admin':
                raise ValueError('Unauthorized index deletion organization')
            return {"result": await self.vectors.delete(source_id=str(payload["id"]), org_id=org_id, kind=index_kind)}
        if kind == "duplicates":
            talent = payload["talent"]
            if str(talent["org_id"]) != str(actor["org_id"]) and actor.get('role') != 'admin':
                raise ValueError("Unauthorized duplicate lookup")
            allowed = [str(key) for key in payload.get("allowed_ids", []) if str(key) != str(talent["id"])]
            hits = await self.vectors.search(json.dumps(talent.get("profile", {}), ensure_ascii=False), allowed_ids=allowed,
                                              org_id=str(talent['org_id']), kind="talent", limit=100) if allowed else []
            seen, suspected = set(), []
            for hit in hits:
                key = str(hit.get("source_id"))
                similarity = float(hit.get("semantic_score", 0))
                if key in allowed and key not in seen and similarity >= .85:
                    seen.add(key)
                    suspected.append({"talent_id": key, "similarity": similarity, "revision": hit.get("revision"),
                                      "evidence": {k: hit.get(k) for k in ("source_id", "source_path", "chunk", "text")},
                                      "action": "manual_review"})
            return {"result": {"suspected_duplicates": suspected[:20], "auto_merged": False}}
        if kind == "index":
            talent = payload["talent"]
            if str(talent["org_id"]) != str(actor["org_id"]) and actor.get('role') != 'admin':
                raise ValueError("Unauthorized index organization")
            return {"result": await self.vectors.upsert(talent, kind="talent")}
        if kind == "job":
            reply = await self.ask({"task": "job", "description": payload["description"],
                                    "schema": {"requirements": {"required_skills": [], "preferred_skills": [], "min_experience_months": None,
                                                                "min_education": None, "location": None, "required_certificates": [], "responsibilities": [], "evidence": []}}}, actor)
            requirements = reply.get("requirements")
            if not isinstance(requirements, dict):
                raise ValueError("Structured job requirements required")
            # Job constraints must be tied to the supplied text before they can hard-filter people.
            evidence = [e for e in requirements.get("evidence", []) if isinstance(e, dict) and e.get("quote") and e["quote"] in payload["description"]]
            for field, value in requirements.items():
                if field == "evidence" or not value:
                    continue
                values = value if isinstance(value, list) else [value]
                for item in values:
                    bound = [e for e in evidence if e.get("field") == field and (
                             normalized(e.get("value")).casefold() == normalized(item).casefold() or
                             isinstance(item, str) and isinstance(e.get('value'), str) and
                             e['value'] in e['quote'] and claim_is_positive(field, item, e['value']))]
                    if field == 'required_skills' and bound and all(
                        re.search(r'优先|加分|preferred|nice.to.have', e['quote'], re.I) and
                        not re.search(r'必须|必备|要求|must|required', e['quote'], re.I) for e in bound):
                        raise ValueError('A preferred skill cannot become a mandatory condition')
                    if bound and not any(claim_is_positive(field, item, e['quote']) or
                            field == 'min_experience_months' and any(claim_is_positive(field, phrase, e['quote'])
                            for phrase in re.findall(r'\d+(?:\.\d+)?\s*年', e['quote'])) for e in bound):
                        raise ValueError('Job requirement evidence negates field: ' + field)
                    if not bound or not any(normalized(item).casefold() in normalized(e["quote"]).casefold() for e in bound):
                        # A numeric month conversion may be explicitly tied to a year phrase.
                        numeric = field == "min_experience_months" and isinstance(item, (int, float)) and any(
                            any(float(n) * 12 == float(item) for n in re.findall(r"(\d+(?:\.\d+)?)\s*年", e["quote"])) for e in bound)
                        if not numeric:
                            raise ValueError("Job requirement evidence does not support field: " + field)
            return {"result": {"requirements": requirements, "versions": self.versions()}}
        raise ValueError("Unsupported talent operation")

    async def _resume_extract(self, state: AgentState) -> dict:
        text = str(state["payload"].get("text", ""))
        if not text.strip() or len(text) > 500_000:
            raise ValueError("Resume plain text must contain 1 to 500000 characters")
        profile = state.get("profile") or ground_profile({}, text)[0]
        before = fact_count(profile)
        issues, conflicts, valid_round = [], [], True
        # Chinese characters can approach one token each. Reserve context for
        # instructions, evidence and output on the 8192-token local model.
        parts = split_documents(text, chunk_size=3000, chunk_overlap=200)
        for index, part in enumerate(parts):
            request = {"task": "resume", "text": part.page_content,
                       "validation_issues": state.get("issues", []), "missing_fields": missing_core_fields(profile),
                       "verified_profile": {field: value for field, value in profile.items() if field != "evidence"},
                       "round": state.get("rounds", 0) + 1, "chunk": index, "chunk_count": len(parts),
                       "instruction": "只提取本段明确陈述的事实。缺失字段留空，不推断；补抽仅补缺失事实，禁止改写已核实事实。每个事实必须有精确原文证据。",
                       "schema": {"profile": {"name": None, "phone": None, "email": None, "location": None,
                                  "skills": [], "education": [], "experiences": [], "projects": [], "certificates": [],
                                  "intentions": [], "evidence": [{"field": "name", "value": "原文值", "quote": "原文精确引用"}]}}}
            try:
                raw = Extraction.model_validate(await self.ask(request, state["actor"])).profile
                incoming, chunk_issues = ground_profile(raw, part.page_content)
                for evidence in incoming.get("evidence", []):
                    evidence["start"] += part.metadata["start_index"]
                    evidence["end"] += part.metadata["start_index"]
                profile, new_conflicts = merge_profiles(profile, incoming)
                conflicts.extend(new_conflicts)
                issues.extend(issue for issue in chunk_issues if issue != "no_grounded_facts")
            except ValueError:
                valid_round = False
                issues.append("invalid_structured_output")
        persistent = [issue for issue in state.get("issues", []) if issue.startswith("conflicting:")]
        return {"profile": profile, "rounds": state.get("rounds", 0) + 1,
                "round_issues": list(dict.fromkeys(issues)), "issues": list(dict.fromkeys(persistent + conflicts + issues)),
                "gained_facts": fact_count(profile) - before, "valid_round": valid_round,
                'execution_summary': state.get('execution_summary', []) + [{'node': 'resume_extract', 'round': state.get('rounds', 0) + 1, 'chunks': len(parts), 'added_facts': fact_count(profile) - before, 'format_valid': valid_round, 'issue_count': len(set(issues + conflicts))}]}

    async def _resume_validate(self, state: AgentState) -> dict:
        profile, rounds = state["profile"], state["rounds"]
        missing = missing_core_fields(profile)
        complete = not missing
        stop_reason = ("core_fields_complete" if complete else "retry_budget_exhausted" if rounds >= 4 else
                       "no_progress" if rounds > 1 and state["valid_round"] and state["gained_facts"] == 0 else None)
        if stop_reason and fact_count(profile) == 0:
            raise ValueError("Resume extraction failed: no grounded facts; " + stop_reason)
        issues = state.get("issues", [])
        profile = {**profile, "anomalies": issues}
        report = {"rounds": rounds, "retry_count": rounds - 1, "quality_status": "complete" if complete else "partial",
                  "missing_fields": missing, "stop_reason": stop_reason, "needs_review": bool(missing or issues),
                  "issues": issues, "input_sha256": hashlib.sha256(state["payload"]["text"].encode()).hexdigest(),
                  'execution_summary': state.get('execution_summary', []) + [{'node': 'resume_validate', 'round': rounds, 'missing_fields': missing, 'stop_reason': stop_reason}],
                  "versions": state.get('versions', {})}
        return {"result": {"profile": profile, "report": report}, "retry_resume": stop_reason is None}

    def versions(self):
        return {"workflow": "talent-platform-v1", "chat_model": os.getenv("CHAT_MODEL", "dify-configured"),
                "embedding_model": os.getenv("EMBEDDING_MODEL", ""), "scoring": "40-25-25-10-projects-v2",
                'chat_model_digest': os.getenv('CHAT_MODEL_DIGEST', ''),
                'embedding_model_digest': os.getenv('EMBEDDING_MODEL_DIGEST', ''),
                'dify_app_id': os.getenv('DIFY_APP_ID', ''), 'prompt_version': os.getenv('PROMPT_VERSION', 'talent-platform-v1'),
                'prompt_sha256': hashlib.sha256(inspect.getsource(model_prompt).encode()).hexdigest(),
                'dify_workflow_sha256': os.getenv('DIFY_WORKFLOW_HASH', '')}

    async def _matching(self, state: AgentState) -> dict:
        payload, actor = state["payload"], state["actor"]
        if state['kind'] == 'search':
            return await self._search(payload, actor)
        org_id = str(payload['job'].get('org_id', actor['org_id']))
        if org_id != str(actor['org_id']) and actor.get('role') != 'admin':
            raise ValueError('Unauthorized job organization')
        talents = {str(t["id"]): t for t in payload.get("talents", []) if str(t["id"]) in set(map(str, payload.get("allowed_ids", [])))
                   and str(t.get('org_id')) == org_id}
        requirements = payload["job"].get("requirements", {})
        # Deterministic hard eligibility runs before retrieval; semantic similarity cannot override a failed condition.
        eligible = {}
        for key, talent in talents.items():
            text = json.dumps(talent.get("profile", {}), ensure_ascii=False)
            provisional = score_candidate(requirements, talent.get("profile", {}), [{"text": text}])
            if provisional["eligible"]:
                eligible[key] = talent
        hits = await self.vectors.search(json.dumps(requirements, ensure_ascii=False), allowed_ids=list(eligible),
                                          org_id=org_id, kind="talent", limit=100) if eligible else []
        groups = {}
        for hit in hits:
            key = str(hit.get("source_id"))
            talent = eligible.get(key)
            if not talent or not current_hit(hit, talent, kind='talent', org_id=org_id):
                continue
            groups.setdefault(key, []).append(hit)
        candidates = []
        for key, chunks in groups.items():
            talent = eligible[key]
            score = score_candidate(requirements, talent.get("profile", {}), chunks)
            if score["eligible"]:
                candidates.append({"talent_id": key, "name": talent.get("profile", {}).get("name"), "revision": talent.get("revision"),
                                   "profile": talent.get("profile", {}), "score": score})
        candidates.sort(key=lambda c: (-c["score"]["total"], c["talent_id"]))
        return {"result": {"candidates": candidates[:20], "diagnostics": {"authorized": len(talents), "hard_eligible": len(eligible),
                          "retrieved_chunks": len(hits), "recall_limit": 100, "output_limit": 20}, "versions": self.versions()}}

    async def _search(self, payload: dict, actor: dict) -> dict:
        query = str(payload.get('query', '')).strip()
        if not query or len(query) > 10000:
            raise ValueError('Search query must contain 1 to 10000 characters')
        allowed = set(map(str, payload.get('allowed_ids', [])))
        talents = {str(t['id']): t for t in payload.get('talents', []) if str(t['id']) in allowed and t.get('org_id')
                   and (str(t['org_id']) == str(actor['org_id']) or actor.get('role') == 'admin')}
        groups = {}
        for talent in talents.values():
            if talent.get('revision') is not None and talent.get('indexed_revision') == talent['revision'] and talent.get('index_model'):
                groups.setdefault(str(talent['org_id']), []).append(str(talent['id']))
        found = {}
        for org_id, ids in groups.items():
            for hit in await self.vectors.search(query, allowed_ids=ids, org_id=org_id, kind='talent', limit=100):
                key = str(hit.get('source_id'))
                snapshot = talents.get(key)
                if key in ids and snapshot and current_hit(hit, snapshot, kind='talent', org_id=org_id):
                    found.setdefault(key, []).append(hit)
        items = [{'talent_id': key, 'revision': talents[key]['revision'], 'profile': talents[key].get('profile', {}),
                  'name': talents[key].get('profile', {}).get('name'), 'similarity': max(float(h.get('semantic_score', 0)) for h in hits),
                  'evidence': hits} for key, hits in found.items()]
        items.sort(key=lambda item: (-item['similarity'], item['talent_id']))
        return {'result': {'items': items[:20], 'total': len(items), 'versions': self.versions()}}

    async def _knowledge(self, state: AgentState) -> dict:
        payload, actor = state["payload"], state["actor"]
        if state["kind"] == "knowledge":
            document = payload["document"]
            if str(document["org_id"]) != str(actor["org_id"]) and actor.get('role') != 'admin':
                raise ValueError("Unauthorized knowledge organization")
            return {"result": await self.vectors.upsert(document, kind="knowledge")}
        documents = [d for d in payload.get("documents", []) if d.get('kind', 'knowledge') in {'knowledge', 'talent'} and
                     (str(d.get("org_id")) == str(actor["org_id"]) or actor.get('role') == 'admin') and
                     (d.get("scope") != "private" or str(d.get("owner_id")) == str(actor["id"]))]
        session = str(payload.get("session_id", ""))
        refusal = {"answer": "现有授权资料没有足够依据回答此问题。", "citations": [], "session_id": session}
        if not documents:
            return {"result": refusal}
        grouped, hits = {}, []
        for document in documents:
            grouped.setdefault((document.get('kind', 'knowledge'), str(document['org_id'])), []).append(str(document['id']))
        for (kind, org_id), ids in grouped.items():
            hits.extend(await self.vectors.search(payload['question'], allowed_ids=ids, org_id=org_id, kind=kind, limit=100))
        authorized = {str(d["id"]): d for d in documents}
        candidates = []
        tokens = set(re.findall(r"\w+", payload["question"].casefold()))
        for d in documents:
            for index, part in enumerate(split_documents(d.get('text', ''))):
                chunk = part.page_content
                keyword = sum(token in chunk.casefold() for token in tokens) / max(1, len(tokens))
                semantic = max([h.get('semantic_score', 0) for h in hits if h.get('chunk') == index and
                                current_hit(h, d, kind=d.get('kind', 'knowledge'), org_id=str(d['org_id'])) and
                                h.get('text') == chunk] or [0])
                if keyword or semantic > .1:
                    candidates.append({"source_id": str(d["id"]), "title": d.get("title", ""), "text": chunk, "chunk": index,
                                       "kind": d.get('kind', 'knowledge'), 'org_id': str(d['org_id']),
                                       "revision": d.get('revision'), "hybrid_score": .55 * semantic + .45 * keyword})
        candidates.sort(key=lambda x: -x["hybrid_score"])
        if not candidates:
            return {"result": refusal}
        # Explicit second-stage cross-document rerank through the same serialized gateway.
        pool = candidates[:30]
        rerank = await self.ask({"task": "rerank", "question": payload["question"], "candidates": pool,
                                 "schema": {"order": [0]}}, actor)
        order = rerank.get("order", [])
        if not isinstance(order, list) or any(type(i) is not int or not 0 <= i < len(pool) for i in order):
            raise ValueError("Invalid rerank response")
        context = [pool[i] for i in dict.fromkeys(order)][:8]
        if not context:
            return {"result": refusal}
        aliases = {'S' + str(index + 1): item['source_id'] for index, item in enumerate(context)}
        model_context = [{'source_id': 'S' + str(index + 1), 'title': item['title'], 'text': item['text']}
                         for index, item in enumerate(context)]
        reply = ChatAnswer.model_validate(await self.ask({"task": "chat", "question": payload["question"], "context": model_context,
                    "history": payload.get("history", [])[-12:], "schema": {"answer": "", "citations": [{"source_id": "", "quote": ""}]}}, actor))
        citations = []
        for item in reply.citations:
            source_id = aliases.get(item.source_id, item.source_id)
            if source_id in authorized and item.quote.strip() and any(c["source_id"] == source_id and item.quote in c["text"] for c in context):
                citation = {"source_id": source_id, "title": authorized[source_id].get("title", ""), "quote": item.quote}
                if authorized[source_id].get('revision') is not None:
                    citation.update(revision=authorized[source_id]['revision'], kind=authorized[source_id].get('kind', 'knowledge'))
                citations.append(citation)
        return {"result": {"answer": reply.answer, "citations": citations, "session_id": session} if citations and len(citations) == len(reply.citations) else refusal}

    async def _development(self, state: AgentState) -> dict:
        payload, actor = state["payload"], state["actor"]
        if state["kind"] == "training":
            aliases = {f'C{i + 1}': str(course['id']) for i, course in enumerate(payload.get('courses', []))}
            courses = [{**course, 'id': alias} for alias, course in zip(aliases, payload.get('courses', []))]
            reply = TrainingAnswer.model_validate(await self.ask({"task": "training", **payload, 'courses': courses,
                       "schema": {"title": "", "course_ids": [], "reasons": {}}}, actor))
            reply.course_ids = [aliases.get(key, key) for key in reply.course_ids]
            reply.reasons = {aliases.get(key, key): value for key, value in reply.reasons.items()}
            allowed = {str(c["id"]) for c in payload.get("courses", [])}
            if any(key not in allowed for key in reply.course_ids) or set(reply.reasons) - set(reply.course_ids):
                raise ValueError("Recommended course is outside authorized course catalog")
            if len(reply.course_ids) != len(set(reply.course_ids)):
                raise ValueError("Duplicate recommended course")
            if not reply.title.strip() or any(not reply.reasons.get(key, '').strip() for key in reply.course_ids):
                raise ValueError('Training plan requires a title and a reason for every selected course')
            return {"result": reply.model_dump()}
        questions, answers = payload.get("questions", []), payload.get("answers", {})
        subjective = [q for q in questions if q.get("question_type") == "text" and answers.get(str(q["id"]))]
        if any(not q.get("rubric") for q in subjective):
            raise ValueError("Subjective assessment requires a scoring rubric")
        judged = {}
        if subjective:
            reply = await self.ask({"task": "assessment", "questions": subjective, "answers": answers,
                                    "schema": {"scores": [{"question_id": "", "points": 0, "feedback": ""}]}}, actor)
            judged = {str(item["question_id"]): item for item in reply.get("scores", [])}
            if set(judged) != {str(q["id"]) for q in subjective}:
                raise ValueError("Incomplete subjective scoring response")
        scores, dimensions, feedback = [], {}, []
        for q in questions:
            qid, maximum = str(q["id"]), max(0, float(q.get("points", 1)))
            given, expected = answers.get(qid), q.get("answer")
            if q.get("question_type") == "text":
                points = max(0, min(maximum, float(judged.get(qid, {}).get("points", 0))))
                feedback.append({"question_id": qid, "feedback": judged.get(qid, {}).get("feedback", "未作答"), "inference": True})
            elif q.get("question_type") == "multiple":
                points = maximum if isinstance(given, list) and isinstance(expected, list) and set(map(str, given)) == set(map(str, expected)) else 0
            elif q.get("question_type") == "single":
                points = maximum if given is not None and given == expected else 0
            else:
                raise ValueError("Unsupported assessment question type")
            scores.append((points, maximum))
            for skill in q.get("skills", []):
                dimensions.setdefault(skill, []).append((points, maximum))
        def percent(values):
            return round(sum(v[0] for v in values) / max(.00001, sum(v[1] for v in values)) * 100, 2)
        risks = [{"type": e.get("type"), "at": e.get("at"), "inference": True} for e in payload.get("events", [])
                 if e.get("type") in {"blur", "paste", "tab_hidden", "fullscreen_exit"}]
        return {"result": {"total": percent(scores), "dimensions": {k: percent(v) for k, v in dimensions.items()},
                           "feedback": feedback, "risks": risks, "inference": True}}

    async def _analytics(self, state: AgentState) -> dict:
        if self.analysis is None:
            from .analysis import AnalyticsEngine
            self.analysis = AnalyticsEngine(model=self.ask)
        return {"result": await self.analysis.execute(state["payload"], actor=state["actor"])}
