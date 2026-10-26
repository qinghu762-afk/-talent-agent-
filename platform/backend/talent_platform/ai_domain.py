"""Deterministic evidence, normalization and scoring rules. No database access."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any


def normalized(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def canonical_skill(value: Any) -> str:
    value = normalized(value)
    aliases = {"python": "Python", "java": "Java", "javascript": "JavaScript", "js": "JavaScript",
               "typescript": "TypeScript", "ts": "TypeScript", "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
               "mysql": "MySQL", "c++": "C++", "sql": "SQL", "react": "React", "vue": "Vue"}
    return aliases.get(value.casefold(), value)


def canonical_phone(value: Any) -> str:
    phone = re.sub(r'[\s()-]', '', normalized(value))
    return re.sub(r'^(?:\+86|0086|86)(?=1[3-9]\d{9}$)', '', phone)


def canonical_degree(value: Any) -> str:
    text = normalized(value)
    aliases = {'大学本科': '本科', '学士': '本科', '学士学位': '本科', 'bachelor': '本科', "bachelor's": '本科',
               '大学专科': '大专', '专科': '大专', '硕士研究生': '硕士', '硕士学位': '硕士', 'master': '硕士',
               "master's": '硕士', '博士研究生': '博士', '博士学位': '博士', 'phd': '博士', 'ph.d.': '博士'}
    return aliases.get(text.casefold(), text)


def canonical_date(value: Any) -> Any:
    if value is None:
        return None
    text = normalized(value)
    if text.casefold() in {'present', 'current', 'now', '至今', '现在'}:
        return '至今'
    found = re.fullmatch(r'(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?月?', text)
    if found and 1 <= int(found[2]) <= 12:
        return f'{found[1]}-{int(found[2]):02d}' + (f'-{int(found[3]):02d}' if found[3] else '')
    return text


def canonical_fact(field: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {({'start_date': 'start', 'end_date': 'end'}.get(key, key)
                 if key not in {'start_date', 'end_date'} or key.removesuffix('_date') not in value else key):
                canonical_degree(piece) if field == 'education' and key == 'degree' else
                canonical_date(piece) if key in {'start', 'end', 'start_date', 'end_date', 'graduation_date'} else piece
                for key, piece in value.items()}
    if field == 'phone':
        return canonical_phone(value)
    if field == 'skills':
        return canonical_skill(value)
    if field == 'education':
        return canonical_degree(value)
    return value


def unique(values: list) -> list[str]:
    result = []
    for value in values:
        item = canonical_skill(value)
        if item and item.casefold() not in {x.casefold() for x in result}:
            result.append(item)
    return result


def token_pattern(value: Any) -> str:
    return r"(?<![a-z0-9_])" + re.escape(normalized(value).casefold()) + r"(?![a-z0-9_])"


def claim_is_positive(field: str, value: Any, text: str) -> bool:
    """Conservative local-language negation/aspiration guard around the actual source occurrence."""
    if isinstance(value, dict):
        return all(claim_is_positive(field, piece, text) for piece in value.values() if piece is not None)
    if isinstance(value, list):
        return all(claim_is_positive(field, piece, text) for piece in value)
    normalized_text = normalized(text).casefold()
    matches = list(re.finditer(token_pattern(value), normalized_text))
    if not matches:
        return False
    for match in matches:
        before = normalized_text[max(0, match.start() - 50):match.start()]
        before = re.split(r"[，,。;；\n]|\bbut\b|但是|不过|然而", before)[-1]
        after = re.split(r"[，,。;；\n]", normalized_text[match.end():match.end() + 25])[0]
        negative = r"\b(?:no|not|never|without|lack|lacks|lacking|unknown|cannot|can't|don't|doesn't)\b|不|未|没有|无|缺乏|待确认"
        if re.search(negative, before):
            return False
        if re.search(r"计划学习|待学习|备考|未取得|未毕业|肄业|not completed|planning to learn", after):
            return False
        if field in {"name", "phone", "email"} and re.search(r"推荐人|证明人|紧急联系人|reference|recruiter", before):
            return False
        if field == "location" and re.search(r"期望|意向|希望|desired|preferred", before):
            return False
    return True


def fact_equal(left: Any, right: Any, field: str) -> bool:
    left, right = canonical_fact(field, left), canonical_fact(field, right)
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return left == right
    if field == "skills":
        return canonical_skill(left).casefold() == canonical_skill(right).casefold()
    if field == 'phone':
        return re.sub(r'[\s()-]', '', normalized(left)) == re.sub(r'[\s()-]', '', normalized(right))
    return normalized(left).casefold() == normalized(right).casefold()


def verified_values(profile: dict, field: str) -> list:
    raw = profile.get(field, [])
    raw = raw if isinstance(raw, list) else [raw] if raw else []
    if profile.get("source") == "manual" and profile.get("verified_by"):
        return raw
    evidence = profile.get("evidence", [])
    return [value for value in raw if any(isinstance(e, dict) and e.get("field", "").split(".")[0] == field and
            fact_equal(e.get("value"), value, field) and
            ((e.get("source") == "manual" and e.get("verified_by")) or
             e.get("source_id") == "input" and e.get("quote") and claim_is_positive(field, e.get('value'), e["quote"]))
            for e in evidence)]


def month_number(value: Any) -> int | None:
    text = normalized(value)
    if text in {"至今", "现在", "present", "Present"}:
        today = date.today()
        return today.year * 12 + today.month
    found = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})(?:[-/.月]\d{1,2}日?)?月?", text)
    if not found:
        return None
    year, month = map(int, found.groups())
    current = date.today()
    return year * 12 + month if 1900 <= year <= current.year and 1 <= month <= 12 and year * 12 + month <= current.year * 12 + current.month else None


def experience_months(experiences: list[dict]) -> tuple[int, bool]:
    """Union known intervals; unknown intervals never erase verified tenure."""
    intervals, unknown = [], False
    for entry in experiences:
        start, end = month_number(entry.get("start", entry.get('start_date'))), month_number(entry.get("end", entry.get('end_date')))
        if start is None or end is None or end < start:
            unknown = True
        else:
            intervals.append((start, end))
    covered, cursor = 0, -1
    for start, end in sorted(intervals):
        covered += max(0, end - max(start, cursor))
        cursor = max(cursor, end)
    return covered, unknown


def ground_profile(raw: dict, source: str) -> tuple[dict, list[str]]:
    """Keep only fields supported by exact source quotes and matching values."""
    evidence, issues = [], []
    text = source
    for item in raw.get("evidence", []):
        if not isinstance(item, dict):
            continue
        quote, value = item.get("quote"), item.get("value")
        if isinstance(quote, str) and quote.strip() and quote in text and value:
            # A quote must support the value, not merely occur somewhere in the document.
            pieces = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else [value]
            identity_quote = item.get("field", "").split(".")[0] in {"name", "phone", "email", "location"}
            quote_start = text.index(quote)
            context = text[max(0, quote_start - 50):quote_start + len(quote) + 25]
            if identity_quote and (len(quote) > 160 or len(quote.splitlines()) > 3):
                continue
            if pieces and any(piece for piece in pieces) and all(normalized(piece).casefold() in normalized(quote).casefold() for piece in pieces if piece is not None) and claim_is_positive(item.get("field", "").split(".")[0], value, context):
                evidence.append({"field": str(item.get("field", "")), "value": value, "quote": quote,
                                 "source_id": "input", "start": text.index(quote), "end": text.index(quote) + len(quote)})

    def supported(field, value):
        return any(e["field"].split(".")[0] == field and fact_equal(e["value"], value, field)
                   for e in evidence)

    profile = {"evidence": evidence, "anomalies": [], "summary": "", "tags": []}
    for field in ("name", "phone", "email", "location"):
        value = normalized(raw.get(field))
        profile[field] = value if value and supported(field, value) else None
        if value and not profile[field]:
            issues.append(f"ungrounded:{field}")
        distinct = {normalized(canonical_fact(field, e["value"])).casefold() for e in evidence if e["field"] == field}
        if len(distinct) > 1:
            profile[field] = None
            issues.append(f"conflicting:{field}")
    if profile["phone"]:
        phone = canonical_phone(profile['phone'])
        if not (re.fullmatch(r"(?:\+?86)?1[3-9]\d{9}", phone) or re.fullmatch(r"0\d{9,11}", phone) or
                re.fullmatch(r"\+[1-9]\d{7,14}", phone)):
            profile["phone"] = None
            issues.append("invalid:phone")
        else:
            profile["phone"] = phone
    if profile["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", profile["email"]):
        profile["email"] = None
        issues.append("invalid:email")
    for field in ("skills", "education", "experiences", "projects", "certificates", "intentions"):
        values = raw.get(field, [])
        if not isinstance(values, list):
            issues.append(f"invalid:{field}")
            values = []
        accepted = [value for value in values if supported(field, value)]
        if field == 'skills':
            categories = {'工程师', '经理', '员工', '主管', '总监', '学历', '本科', '硕士', '博士',
                          'engineer', 'manager', 'employee', 'director', 'bachelor', 'master', 'phd'}
            concrete = [value for value in accepted if normalized(value).casefold() not in categories]
            if len(concrete) != len(accepted):
                issues.append('invalid:skills_category')
            accepted = concrete
        if len(accepted) != len(values):
            issues.append(f"ungrounded:{field}")
        profile[field] = unique(accepted) if field == "skills" else [canonical_fact(field, value) for value in accepted]
    for item in evidence:
        item['normalized_value'] = canonical_fact(item['field'].split('.')[0], item['value'])
    profile["experience_months"], unknown = experience_months([e for e in profile["experiences"] if isinstance(e, dict)])
    if unknown:
        issues.append("unknown:experience_dates")
    profile["completeness"] = round(sum(bool(profile.get(k)) for k in
                                           ("name", "phone", "email", "location", "skills", "education", "experiences", "projects")) / 8, 3)
    profile["anomalies"] = issues
    if not evidence:
        issues.append("no_grounded_facts")
    enrich_verified_profile(profile)
    return profile, issues


def enrich_verified_profile(profile: dict) -> None:
    """Describe verified source facts without evaluating ability or potential."""
    skills = unique(verified_values(profile, 'skills'))
    education = verified_values(profile, 'education')
    experiences = verified_values(profile, 'experiences')
    projects = verified_values(profile, 'projects')
    profile['tags'] = skills
    sections, fields = [], []
    if skills:
        sections.append('技能：' + '、'.join(skills[:12]))
        fields.append('skills')
    def describe(value, keys):
        return ' / '.join(normalized(value[key]) for key in keys if value.get(key)) if isinstance(value, dict) else normalized(value)
    for field, label, values, keys in (
        ('education', '教育', education, ('school', 'institution', 'degree', 'major')),
        ('experiences', '经历', experiences, ('company', 'organization', 'role', 'title', 'start', 'end')),
        ('projects', '项目', projects, ('name', 'title', 'role', 'description', 'start', 'end'))):
        descriptions = [describe(value, keys) for value in values[:5]]
        descriptions = [value for value in descriptions if value]
        if descriptions:
            sections.append(label + '：' + '；'.join(descriptions))
            fields.append(field)
    profile['summary'] = '。'.join(sections)[:4000]
    profile['derived_fields'] = {'summary': {'method': 'verified_fact_template', 'source_fields': fields, 'inference': False},
                                 'tags': {'method': 'canonical_verified_skills', 'source_fields': ['skills'] if skills else [], 'inference': False}}


FACT_FIELDS = ('name', 'phone', 'email', 'location', 'skills', 'education', 'experiences', 'projects', 'certificates', 'intentions')


def fact_count(profile: dict) -> int:
    return sum(len(profile.get(field, [])) if isinstance(profile.get(field), list) else bool(profile.get(field))
               for field in FACT_FIELDS)


def missing_core_fields(profile: dict) -> list[str]:
    return [field for field, present in (
        ('name', profile.get('name')), ('contact', profile.get('phone') or profile.get('email')),
        ('skills', profile.get('skills')), ('education_or_experiences', profile.get('education') or profile.get('experiences')))
        if not present]


def merge_profiles(previous: dict, incoming: dict) -> tuple[dict, list[str]]:
    """Append verified facts; a later round cannot silently replace an identity."""
    merged = {**previous}
    conflicts = []
    for field in FACT_FIELDS:
        old, new = merged.get(field), incoming.get(field)
        if isinstance(new, list):
            values = list(old or [])
            for value in new:
                if not any(fact_equal(value, item, field) for item in values):
                    values.append(value)
            merged[field] = values
        elif new:
            if old and not fact_equal(old, new, field):
                conflicts.append('conflicting:' + field)
            else:
                merged[field] = new
        else:
            merged.setdefault(field, None)
    evidence = list(previous.get('evidence', []))
    for item in incoming.get('evidence', []):
        field = item.get('field', '').split('.')[0]
        values = merged.get(field, [])
        values = values if isinstance(values, list) else [values]
        if any(fact_equal(item.get('value'), value, field) for value in values) and item not in evidence:
            evidence.append(item)
    merged['evidence'] = evidence
    merged['experience_months'], _ = experience_months([v for v in merged.get('experiences', []) if isinstance(v, dict)])
    merged['completeness'] = round(sum(bool(merged.get(k)) for k in
                                      ('name', 'phone', 'email', 'location', 'skills', 'education', 'experiences', 'projects')) / 8, 3)
    enrich_verified_profile(merged)
    return merged, conflicts


def score_candidate(requirements: dict, profile: dict, hits: list[dict]) -> dict:
    import json
    required = unique(requirements.get("required_skills", []))
    preferred = unique(requirements.get("preferred_skills", []))
    skillset = {canonical_skill(x).casefold() for x in verified_values(profile, "skills")}
    hit_text = "\n".join(str(h.get("text", "")) for h in hits).casefold()
    # Project evidence is the very chunk retrieved, never a different project in the profile.
    def present(skill):
        return skill.casefold() in skillset and claim_is_positive("skills", skill, hit_text)
    verified_experiences = verified_values(profile, "experiences")
    months, unknown_dates = experience_months([e for e in verified_experiences if isinstance(e, dict)])
    unknown_dates = unknown_dates or not verified_experiences
    minimum = requirements.get("min_experience_months")
    level_order = {"高中": 1, "中专": 1, "大专": 2, "专科": 2, "本科": 3, "学士": 3, "硕士": 4, "博士": 5}
    education = [entry for entry in verified_values(profile, "education") if not isinstance(entry, dict) or
                 entry.get("status") not in {"在读", "肄业", "未毕业", "studying", "incomplete"}]
    level = max([level_order.get(canonical_degree(e.get('degree', '') if isinstance(e, dict) else e), 0) for e in education] or [0])
    min_level = canonical_degree(requirements.get("min_education"))
    conditions, gaps, unknowns, strengths = [], [], [], []

    def condition(name, passed, known=True):
        status = "pass" if passed else "fail" if known else "unknown"
        conditions.append({"name": name, "status": status})
        (strengths if passed else gaps if known else unknowns).append(name)

    for skill in required:
        condition("skill:" + skill, present(skill), bool(skillset))
    if minimum is not None:
        condition("experience", months >= float(minimum), months >= float(minimum) or not unknown_dates)
    if unknown_dates:
        unknowns.append("部分经历日期未核实；已验证年限仍有效")
    if min_level:
        condition("education", level >= level_order.get(str(min_level), 999), bool(level))
    location = requirements.get("location")
    if location:
        verified_locations = verified_values(profile, "location")
        condition("location", normalized(location) in list(map(normalized, verified_locations)), bool(verified_locations))
    for certificate in requirements.get("required_certificates", []):
        certificates = verified_values(profile, "certificates")
        condition("certificate:" + str(certificate), any(fact_equal(certificate, item, "certificates") for item in certificates), bool(certificates))
    def configured_values(field):
        value = requirements.get(field, [])
        return [value] if isinstance(value, str) and value.strip() else list(value or [])

    project_requirements = configured_values('project_requirements') or configured_values('responsibilities')
    experience_requirements = configured_values('experience_requirements')
    preferred_certificates = configured_values('preferred_certificates')

    def bound_record_hits(field, records):
        """A global skill hit cannot stand in for a verified project or work record."""
        import math
        def pieces(value):
            if isinstance(value, dict):
                return [piece for item in value.values() for piece in pieces(item)]
            if isinstance(value, list):
                return [piece for item in value for piece in pieces(item)]
            return [normalized(value)] if value is not None and normalized(value) else []
        bound = []
        marker = r'项目|project' if field == 'projects' else r'经历|工作|experience|employment|company'
        for record in records:
            values = pieces(record)
            if not values:
                continue
            for hit in hits:
                similarity = hit.get('semantic_score')
                if isinstance(similarity, bool) or not isinstance(similarity, (int, float)) or not math.isfinite(similarity):
                    continue
                text = str(hit.get('text', ''))
                # Actual retrieval metadata and a record-specific value binding are mandatory.
                if not hit.get('source_id') or type(hit.get('chunk')) is not int or not re.search(marker, text, re.IGNORECASE):
                    continue
                if not all(normalized(value).casefold() in normalized(text).casefold() for value in values):
                    continue
                if not claim_is_positive(field, record, text):
                    continue
                source = next((e for e in profile.get('evidence', []) if isinstance(e, dict) and
                               e.get('field', '').split('.')[0] == field and fact_equal(e.get('value'), record, field)), {})
                compact = re.sub(r'\s+', '', normalized(text)).casefold()
                serialized = re.sub(r'\s+', '', json.dumps(record, ensure_ascii=False)).casefold()
                original_quote = source.get('quote')
                source_binding = isinstance(original_quote, str) and original_quote in text and all(
                    normalized(value).casefold() in normalized(original_quote).casefold() for value in values)
                consecutive = r'[\s，,。:：;/、\-–—]{0,20}'.join(re.escape(value.casefold()) for value in values)
                if serialized not in compact and not source_binding and not re.search(consecutive, normalized(text).casefold()):
                    continue
                bound.append({'project' if field == 'projects' else 'experience': record,
                              'semantic_score': max(0.0, min(1.0, float(similarity))), 'inference': True,
                              'source_id': str(hit['source_id']), 'source_path': hit.get('source_path'),
                              'chunk': hit['chunk'], 'revision': hit.get('revision'), 'quote': text,
                              'source_quote': source.get('quote'),
                              'method': 'verified_record_bound_retrieval_similarity'})
        bound.sort(key=lambda item: (-item['semantic_score'], item['source_id'], item['chunk']))
        return bound

    project_evidence = bound_record_hits('projects', verified_values(profile, 'projects')) if project_requirements else []
    targets = list(dict.fromkeys(required + project_requirements + experience_requirements))
    related_records, experience_evidence = [], []
    for record in verified_experiences:
        if not isinstance(record, dict):
            continue
        source = next((e for e in profile.get('evidence', []) if isinstance(e, dict) and
                       e.get('field', '').split('.')[0] == 'experiences' and fact_equal(e.get('value'), record, 'experiences')), {})
        text = json.dumps(record, ensure_ascii=False)
        quote = source.get('quote', '')
        matched = [target for target in targets if claim_is_positive('experiences', target, text) or
                   quote and claim_is_positive('experiences', target, quote)]
        if not targets or matched:
            related_records.append(record)
            experience_evidence.append({'experience': record, 'source_quote': quote or None, 'matched_terms': matched,
                                        'inference': bool(targets), 'method': 'verified_experience_term_binding' if targets else 'verified_tenure'})
    related_months, _ = experience_months(related_records)
    project_score = max((item['semantic_score'] for item in project_evidence), default=0.0)
    experience_score = min(1.0, related_months / float(minimum)) if minimum and float(minimum) > 0 else None
    if experience_requirements and experience_score is None:
        experience_score = float(bool(related_records))
    certificates = verified_values(profile, 'certificates')
    bonus_values = [present(skill) for skill in preferred] + [
        any(fact_equal(certificate, item, 'certificates') for item in certificates) for certificate in preferred_certificates]
    raw = {
        'skills': sum(present(skill) for skill in required) / len(required) if required else None,
        'experience': experience_score,
        'projects': project_score if project_requirements else None,
        'bonus': sum(bonus_values) / len(bonus_values) if bonus_values else None,
    }
    weights = {'skills': .4, 'experience': .25, 'projects': .25, 'bonus': .1}
    active_weight = sum(weights[key] for key, value in raw.items() if value is not None)
    if not active_weight:
        gaps.append('岗位没有可评分条件')
    if project_requirements:
        if project_evidence and project_score > 0:
            best = project_evidence[0]
            strengths.append(f"项目语义相关度 {project_score * 100:.2f}%（检索相似度推断，来源 {best['source_id']} 分块 {best['chunk']}）")
        else:
            gaps.append('缺少与实际命中分块绑定的已核实项目证据')
    if (experience_requirements or minimum) and not experience_evidence:
        gaps.append('缺少与岗位要求绑定的已核实相关经历证据')
    total = round(sum(weights[key] * value for key, value in raw.items() if value is not None) / active_weight * 100, 2) if active_weight else 0
    eligible = bool(active_weight) and all(condition['status'] == 'pass' for condition in conditions)
    return {'eligible': eligible, 'total': total, 'dimensions': {
        key: {'score': round(value * 100, 2) if value is not None else None, 'weight': weights[key],
              'normalized_weight': weights[key] / active_weight if value is not None and active_weight else 0}
        for key, value in raw.items()}, 'conditions': conditions, 'strengths': strengths, 'gaps': gaps,
        'unknowns': unknowns, 'evidence': hits, 'verified_experience_months': months,
        'verified_related_experience_months': related_months,
        'project_evidence': project_evidence[:20], 'experience_evidence': experience_evidence[:20]}
