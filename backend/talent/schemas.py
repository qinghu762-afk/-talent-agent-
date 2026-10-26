from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Schema):
    quote: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    start: int | None = Field(default=None, ge=0)
    source_id: str | None = None


class Experience(Schema):
    company: str | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str = ""
    skills: list[str] = Field(default_factory=list)


class Education(Schema):
    school: str | None = None
    degree: str | None = None
    major: str | None = None


class Project(Schema):
    name: str = ""
    description: str = ""
    skills: list[str] = Field(default_factory=list)


class TalentProfile(Schema):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    location: str | None = None
    education: list[Education] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    intentions: list[str] = Field(default_factory=list)
    evidence: dict[str, list[Evidence]] = Field(default_factory=dict)
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    experience_months: int = 0
    completeness: float = 0


class JobRequirements(Schema):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_experience_months: int | None = Field(default=None, ge=0, le=1200)
    min_education: str | None = None
    required_certificates: list[str] = Field(default_factory=list)
    location: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    evidence: dict[str, list[Evidence]] = Field(default_factory=dict)


class Condition(Schema):
    label: str
    status: Literal["pass", "fail", "unknown"]
    evidence: str


class Dimension(Schema):
    key: str
    label: str
    score: float
    weight: float
    evidence: list[str]


class MatchScore(Schema):
    eligible: bool
    total: float
    dimensions: list[Dimension]
    conditions: list[Condition]
    strengths: list[str]
    gaps: list[str]
    unknowns: list[str]


class IdentityDecision(Schema):
    decision: Literal["merge", "distinct", "conflict"]
    reason: str


class FieldEvidence(Schema):
    field: str = Field(description="字段路径，例如name、skills.0、experiences.0.start、min_experience_months")
    quote: str = Field(min_length=1, description="文档原文的连续片段，必须逐字复制")


class ExtractedEducation(Schema):
    school: str | None = Field(description="学校名称")
    degree: str | None = Field(description="学历或学位")
    major: str | None = Field(description="专业")


class ExtractedExperience(Schema):
    company: str | None = Field(description="任职公司名称，例如在甲公司任职中的甲公司")
    title: str | None = Field(description="职位名称，例如担任后端工程师中的后端工程师")
    start: str | None = Field(description="工作开始日期，逐字复制原文日期，不改写")
    end: str | None = Field(description="工作结束日期，逐字复制原文日期，至今写至今")
    description: str = Field(description="工作内容的原文连续片段，无则空字符串")
    skills: list[str] = Field(description="该段工作实际使用的技能")


class ExtractedProject(Schema):
    name: str = Field(description="项目名称，无则空字符串")
    description: str = Field(description="项目内容的原文连续片段，无则空字符串")
    skills: list[str] = Field(description="该项目明确使用的技能")


class ResumeExtraction(Schema):
    """Only source facts. Required slots keep small local models from skipping whole sections."""
    name: str | None = Field(description="姓名，未知为null")
    phone: str | None = Field(description="电话号码，未知为null")
    email: str | None = Field(description="邮箱，未知为null")
    location: str | None = Field(description="所在地城市，未知为null")
    education: list[ExtractedEducation] = Field(description="逐条教育经历；无则空数组")
    experiences: list[ExtractedExperience] = Field(description="逐条工作经历，必须抽取company公司、title职务、start开始日期、end结束日期")
    projects: list[ExtractedProject] = Field(description="逐条项目经历，包含项目名称name和原文描述description")
    skills: list[str] = Field(description="原文明确提到的技能")
    certificates: list[str] = Field(description="原文明确提到的证书")
    intentions: list[str] = Field(description="原文明确提到的求职意向")
    evidence: list[FieldEvidence] = Field(description="每个非空事实的原文引用；field必须为对应字段路径，不能遗漏")


class JobExtraction(Schema):
    required_skills: list[str] = Field(description="必须具备的技能；优先项不要放这里")
    preferred_skills: list[str] = Field(description="优先或加分技能")
    min_experience_months: int | None = Field(description="最低工作经验，单位月。三年写36，不要求则null")
    min_education: str | None = Field(description="必须达到的最低学历，不要求则null")
    required_certificates: list[str] = Field(description="必须持有的证书")
    location: str | None = Field(description="工作地点城市，不要求则null")
    responsibilities: list[str] = Field(description="工作职责原文；学历和工作年限不属于职责")
    evidence: list[FieldEvidence] = Field(description="每个非空要求的原文引用，field用对应字段名或列表项路径")

