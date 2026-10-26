"""Deterministic rules. Model output is untrusted until grounded in the source."""
import re
import unicodedata
from datetime import date

from .schemas import (
    Condition,
    Dimension,
    IdentityDecision,
    JobRequirements,
    MatchScore,
    TalentProfile,
)

ALIASES = {
    "python": "Python", "python3": "Python", "py": "Python",
    "js": "JavaScript", "javascript": "JavaScript", "ts": "TypeScript",
    "typescript": "TypeScript", "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "sql": "SQL", "java": "Java", "golang": "Go", "go": "Go",
    "react": "React", "reactjs": "React", "vue": "Vue", "vuejs": "Vue",
    "mysql": "MySQL", "redis": "Redis", "docker": "Docker",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes", "c++": "C++",
    "c#": "C#", "pmp": "PMP", "机器学习": "机器学习", "ml": "机器学习",
    "人工智能": "人工智能", "ai": "人工智能", "excel": "Excel",
}
EDUCATION = {"高中": 1, "中专": 1, "大专": 2, "专科": 2, "本科": 3, "学士": 3,
             "bachelor": 3, "硕士": 4, "master": 4, "博士": 5, "phd": 5}


def normalized(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def canonical_skill(value):
    clean = str(value).strip()
    return ALIASES.get(normalized(clean).replace(".js", "js"), clean)


def normalize_contact(value, kind):
    if not value:
        return None
    if kind == "email":
        clean = value.strip().casefold()
        return clean if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean) else None
    clean = re.sub(r"[^\d+]", "", value)
    if clean.startswith("+86") and len(clean) == 14:
        clean = clean[3:]
    elif clean.startswith("0086"):
        clean = clean[4:]
    return clean if re.fullmatch(r"\+?\d{7,15}", clean) else None


def month_index(value, today, ongoing=False):
    if not value or normalized(value) in {"至今", "present", "now", "current"}:
        return today.year * 12 + today.month - 1 if ongoing else None
    match = re.fullmatch(r"(\d{4})[-./年](\d{1,2})月?", value.strip())
    if not match or not 1 <= int(match[2]) <= 12:
        return None
    return int(match[1]) * 12 + int(match[2]) - 1


def experience_months(experiences, today=None):
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    intervals = []
    for exp in experiences:
        start = month_index(exp.start, today)
        # An absent end is unknown, not evidence of current employment.
        end = month_index(exp.end, today, ongoing=bool(exp.end))
        if start is not None and end is not None and start < end and start <= now:
            intervals.append((start, min(end, now)))
    months = 0
    last = -1
    for start, end in sorted(intervals):
        months += max(0, end - max(start, last))
        last = max(last, end)
    return months


def education_rank(value):
    text = normalized(value)
    if re.search(r"肄业|在读|未毕业|未取得|未获得|未完成|incomplete|inprogress|dropout|notobtained", text):
        return 0
    return max((rank for term, rank in EDUCATION.items() if term in text), default=0)


def assess_identity(a, b):
    if not a.name or not b.name or normalized(a.name) != normalized(b.name):
        return IdentityDecision(decision="distinct", reason="姓名不一致或缺失")
    matched = False
    for kind in ("phone", "email"):
        left = normalize_contact(getattr(a, kind), kind)
        right = normalize_contact(getattr(b, kind), kind)
        if left and right:
            if left != right:
                return IdentityDecision(decision="conflict", reason="联系方式存在冲突，保留独立档案")
            matched = True
    return IdentityDecision(decision="merge" if matched else "distinct",
                            reason="姓名及联系方式一致" if matched else "缺少一致的身份凭据")


def value_in_quote(value, quote, key):
    if ("skills" in key or "certificates" in key or key.endswith("degree") or key == "min_education"):
        if re.search(r"不具备|不掌握|不会|未取得|未获得|未通过|没有|缺乏|缺少|\b(?:no|without|lack|lacks)\b|\bnot\s+(?:obtained|certified|skilled)\b", quote, re.I):
            # Positive facts must be quoted from their own non-negated clause.
            return False
    if "skills" in key:
        pattern = r"[A-Za-z][A-Za-z0-9+#.]*|[\u4e00-\u9fff]+"
        canonical = canonical_skill(value)
        if canonical in [canonical_skill(t) for t in re.findall(pattern, quote)]:
            return True
        return bool(re.search(r"[\u4e00-\u9fff]", canonical)) and normalized(canonical) in normalized(quote)
    if normalized(value) in normalized(quote):
        return True
    if key.endswith(("phone", "email")):
        return normalized(value) in normalized(re.sub(r"[\s+().-]", "", quote))
    if key.endswith("end") and normalized(value) in {"至今", "present", "now", "current"}:
        return bool(re.search(r"至今|\b(?:present|now|current)\b", quote, re.IGNORECASE))
    if key.endswith(("start", "end")):
        value_month = month_index(str(value), date.today())
        source_months = [int(y) * 12 + int(m) - 1 for y, m in
                         re.findall(r"(\d{4})[-./年](\d{1,2})月?", quote) if 1 <= int(m) <= 12]
        return value_month is not None and value_month in source_months
    return False


def validate_evidence(profile, text):
    data = profile.model_dump()
    valid = {}
    for key, entries in profile.evidence.items():
        accepted = []
        for ev in entries:
            position = text.find(ev.quote)
            if position >= 0:
                accepted.append(ev.model_copy(update={"start": position, "page": None}))
        if accepted:
            valid[key] = accepted
    anomalies = []

    def meaningful(value):
        if isinstance(value, dict):
            return any(meaningful(v) for v in value.values())
        if isinstance(value, list):
            return any(meaningful(v) for v in value)
        return bool(value.strip()) if isinstance(value, str) else bool(value)

    def grounded(value, key):
        if value is None or value == "":
            return value
        entries = valid.get(key, []) or valid.get(key.split(".")[0], [])
        if isinstance(value, list):
            output = [grounded(item, f"{key}.{i}") for i, item in enumerate(value)]
            return [item for item in output if meaningful(item)]
        if isinstance(value, dict):
            return {k: grounded(v, f"{key}.{k}") for k, v in value.items()}
        # Evidence for a containing object may support its individual leaves.
        if not entries:
            parent = key.rsplit(".", 1)[0]
            while parent:
                entries = valid.get(parent, [])
                if entries or "." not in parent:
                    break
                parent = parent.rsplit(".", 1)[0]
        def supported(ev):
            if not value_in_quote(value, ev.quote, key):
                return False
            if "skills" in key or "certificates" in key or key.endswith("degree"):
                # A one-word quote must not hide the surrounding source negation.
                # The quote may itself include a delimiter. Select source clauses by
                # overlap with the verified span, retaining surrounding negation.
                left, right = ev.start, ev.start + len(ev.quote)
                contexts = [match.group() for match in re.finditer(r"[^，,；;。！？\n]+", text)
                            if match.start() < right and match.end() > left]
                return any(value_in_quote(value, c, key) for c in contexts)
            return True
        if any(supported(ev) for ev in entries):
            return value
        if key in {"phone", "email"}:
            contacts = {normalize_contact(ev.quote, key) for ev in entries
                        if key == "email" or re.fullmatch(r"[+\d()\s.-]+", ev.quote)} - {None}
            if len(contacts) == 1:
                anomalies.append(f"{key} 已按已验证的原文引用纠正")
                return contacts.pop()
        if key.endswith((".start", ".end")):
            # Repair a malformed model date only when a verified quote is exactly one valid source date.
            for ev in entries:
                if month_index(ev.quote, date.today()) is not None:
                    anomalies.append("工作经历日期已按原文引用纠正")
                    return ev.quote
        anomalies.append(f"{key} 缺少可验证的原文依据")
        return None

    for key in ("name", "phone", "email", "location", "skills", "certificates", "intentions",
                "education", "experiences", "projects"):
        data[key] = grounded(data[key], key)
    for key in ("experiences", "projects"):
        for item in data[key]:
            for field in ("description", "name"):
                if field in item and item[field] is None:
                    item[field] = ""
    data["evidence"] = {k: [e.model_dump() for e in v] for k, v in valid.items()}
    data["anomalies"] = anomalies
    data["skills"] = sorted({canonical_skill(s) for s in data["skills"]})
    for kind in ("phone", "email"):
        original = data[kind]
        data[kind] = normalize_contact(original, kind)
        if original and not data[kind]:
            anomalies.append(f"{kind} 格式无效")
    clean = TalentProfile.model_validate(data)
    for exp in clean.experiences:
        for field in ("start", "end"):
            value = getattr(exp, field)
            if value and normalized(value) in {"至今", "present", "now", "current"}:
                setattr(exp, field, "至今")
            elif value:
                index = month_index(value, date.today())
                if index is not None:
                    setattr(exp, field, f"{index // 12:04d}-{index % 12 + 1:02d}")
    clean.experience_months = experience_months(clean.experiences)
    for exp in clean.experiences:
        if exp.start and (month_index(exp.start, date.today()) is None or
                          (exp.end and month_index(exp.end, date.today(), True) is None)):
            clean.anomalies.append("工作经历日期无法确认")
        elif exp.start and exp.end and month_index(exp.start, date.today()) is not None:
            if month_index(exp.start, date.today()) >= month_index(exp.end, date.today(), True):
                clean.anomalies.append("工作经历起止日期顺序异常")
    derive_portrait(clean)
    # Rebuild leaf paths after normalization/filtering/deduplication. Original model indices are untrusted.
    rebuilt = {}
    def locate(value, path):
        if isinstance(value, list):
            for i, item in enumerate(value):
                locate(item, f"{path}.{i}")
        elif isinstance(value, dict):
            for key, item in value.items():
                locate(item, f"{path}.{key}")
        elif value:
            root = path.split(".")[0]
            entries = [ev for old_path, evidence in valid.items() if old_path.split(".")[0] == root
                       for ev in evidence if value_in_quote(value, ev.quote, path)]
            if entries:
                rebuilt[path] = list({(ev.quote, ev.start, ev.source_id): ev for ev in entries}.values())
    for key in ("name", "phone", "email", "location", "skills", "certificates", "intentions", "education", "experiences", "projects"):
        locate(clean.model_dump()[key], key)
    clean.evidence = rebuilt
    return clean


def derive_portrait(profile):
    profile.skills = list(dict.fromkeys(canonical_skill(s) for s in profile.skills))
    profile.experience_months = experience_months(profile.experiences)
    profile.tags = list(dict.fromkeys(profile.skills + [e.title for e in profile.experiences if e.title]))[:20]
    parts = [profile.name or "姓名未知", " / ".join(profile.skills[:8]) or "技能待补充"]
    if profile.experience_months:
        parts.append(f"已验证工作经历 {profile.experience_months} 个月")
    profile.summary = "；".join(parts)
    profile.completeness = round(sum(bool(getattr(profile, key)) for key in (
        "name", "phone", "email", "location", "education", "experiences", "projects", "skills")) / 8 * 100, 1)
    return profile


def score_candidate(profile: TalentProfile, requirements: JobRequirements, semantic_similarity=0):
    skills = {canonical_skill(s) for s in profile.skills}
    required = {canonical_skill(s) for s in requirements.required_skills}
    preferred = {canonical_skill(s) for s in requirements.preferred_skills}
    conditions = []

    def condition(label, known, passed, evidence):
        conditions.append(Condition(label=label, status="unknown" if not known else "pass" if passed else "fail",
                                    evidence=evidence))

    for skill in sorted(required):
        condition(f"必备技能：{skill}", bool(skills), skill in skills,
                  f"简历技能：{', '.join(sorted(skills))}" if skills else "未提供技能依据")
    if requirements.min_experience_months is not None:
        known = bool(profile.experiences) and all(e.start and e.end for e in profile.experiences)
        condition(f"工作经验 ≥ {requirements.min_experience_months} 个月", known,
                  profile.experience_months >= requirements.min_experience_months,
                  f"可验证且去重的工作经历 {profile.experience_months} 个月")
    if requirements.min_education:
        rank = max((education_rank(e.degree) for e in profile.education), default=0)
        required_rank = education_rank(requirements.min_education)
        condition(f"学历 ≥ {requirements.min_education}", bool(rank and required_rank), rank >= required_rank,
                  "、".join(e.degree for e in profile.education if e.degree) or "学历未知")
    if requirements.location:
        condition(f"工作地点：{requirements.location}", bool(profile.location),
                  normalized(profile.location) == normalized(requirements.location), profile.location or "地点未知")
    for cert in requirements.required_certificates:
        condition(f"必备证书：{cert}", bool(profile.certificates),
                  normalized(cert) in {normalized(c) for c in profile.certificates},
                  "、".join(profile.certificates) or "证书未知")
    dims = []
    if required:
        dims.append(Dimension(key="skills", label="技能覆盖", score=100 * len(skills & required) / len(required),
                              weight=.4, evidence=sorted(skills & required)))
    if requirements.min_experience_months is not None:
        target = requirements.min_experience_months
        # Only experiences explicitly related by required/preferred skills count for the soft score.
        terms = required | preferred
        related = [e for e in profile.experiences if not terms or terms & {canonical_skill(s) for s in e.skills}
                   or any(value_in_quote(s, (e.title or "") + "；" + e.description, "skills") for s in terms)]
        months = experience_months(related)
        dims.append(Dimension(key="experience", label="相关经验", score=min(1, months / max(1, target)) * 100,
                              weight=.25, evidence=[f"相关且去重的工作经历 {months} 个月"]))
    if requirements.responsibilities:
        project_score = max(0, min(1, semantic_similarity)) * 100 if profile.projects else 0
        dims.append(Dimension(key="projects", label="项目相关性", score=project_score, weight=.25,
                              evidence=[p.name + "：" + p.description for p in profile.projects][:5]))
    if preferred:
        dims.append(Dimension(key="preferred", label="岗位加分项", score=100 * len(skills & preferred) / len(preferred),
                              weight=.1, evidence=sorted(skills & preferred)))
    weight_sum = sum(d.weight for d in dims)
    for d in dims:
        d.weight /= weight_sum
        d.score = round(d.score, 2)
    unknowns = [c.label for c in conditions if c.status == "unknown"]
    if not dims:
        unknowns.append("岗位尚无可评分的要求")
    strengths = [c.label for c in conditions if c.status == "pass"] + [f"加分技能：{s}" for s in sorted(skills & preferred)]
    gaps = [c.label for c in conditions if c.status == "fail"] + [f"缺少加分技能：{s}" for s in sorted(preferred - skills)]
    return MatchScore(eligible=all(c.status == "pass" for c in conditions),
                      total=round(sum(d.score * d.weight for d in dims), 2), dimensions=dims,
                      conditions=conditions, strengths=strengths, gaps=gaps, unknowns=unknowns)

