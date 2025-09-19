from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, conint, confloat, ConfigDict


class GenerationStatisticsSchema(BaseModel):
    model_name: str
    input_time: float = 0.0
    output_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_time: float = 0.0
    # Avoid warning: Field "model_name" has conflict with protected namespace "model_"
    model_config = ConfigDict(protected_namespaces=())


class StructureParams(BaseModel):
    model: str = Field(default="openai/gpt-oss-20b")
    temperature: confloat(ge=0.0, le=1.0) = 0.3
    top_p: confloat(ge=0.1, le=1.0) = 1.0
    max_tokens: conint(ge=256, le=8000) = 8000
    language: str = Field(default="hu")
    include_intro: bool = False
    include_conclusion: bool = False
    depth: conint(ge=1, le=4) = 2
    extra_instructions: Optional[str] = None


class SectionParams(BaseModel):
    model: str = Field(default="openai/gpt-oss-120b")
    temperature: confloat(ge=0.0, le=1.0) = 0.3
    top_p: confloat(ge=0.1, le=1.0) = 1.0
    max_tokens: conint(ge=256, le=8000) = 8000
    language: str = Field(default="hu")
    style: Optional[str] = Field(default=None, description="e.g., akadémikus, közérthető, narratív, technikai")
    reading_level: Optional[str] = Field(default=None, description="általános, közép, egyetemi, szakértő")
    target_length: Optional[conint(ge=200, le=4000)] = 1200
    parallelism: conint(ge=1, le=1) = 1  # fix 1 by requirement
    extra_instructions: Optional[str] = None


class StructureRequest(BaseModel):
    subject: str
    params: StructureParams = StructureParams()


class StructureResponse(BaseModel):
    statistics: GenerationStatisticsSchema
    structure: Dict[str, Any]


class SectionsStreamRequest(BaseModel):
    structure: Dict[str, Any]
    params: SectionParams = SectionParams()
    start_index: Optional[int] = 0
    count: Optional[int] = None


class ExportRequest(BaseModel):
    content: str
    filename: Optional[str] = "generated_book"
