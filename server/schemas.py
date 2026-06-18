from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, conint, confloat, ConfigDict


class MCPConfig(BaseModel):
    enabled: bool = False
    server_url: str = ""
    auth_token: Optional[str] = None
    label: str = ""           # optional display name for the server
    pre_structure: bool = True
    per_section: bool = True
    max_results: conint(ge=1, le=10) = 3


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
    model: str = Field(default="meta-llama/llama-4-scout-17b-16e-instruct")
    temperature: confloat(ge=0.0, le=1.0) = 0.3
    top_p: confloat(ge=0.1, le=1.0) = 1.0
    max_tokens: conint(ge=256, le=8000) = 4096
    language: str = Field(default="hu")
    include_intro: bool = False
    include_conclusion: bool = False
    depth: conint(ge=1, le=4) = 2
    num_chapters: conint(ge=3, le=50) = 15
    extra_instructions: Optional[str] = None


class SectionParams(BaseModel):
    model: str = Field(default="meta-llama/llama-4-scout-17b-16e-instruct")
    temperature: confloat(ge=0.0, le=1.0) = 0.3
    top_p: confloat(ge=0.1, le=1.0) = 1.0
    max_tokens: conint(ge=256, le=8000) = 4096
    language: str = Field(default="hu")
    style: Optional[str] = Field(default=None, description="e.g., akadémikus, közérthető, narratív, technikai")
    reading_level: Optional[str] = Field(default=None, description="általános, közép, egyetemi, szakértő")
    target_length: Optional[conint(ge=200, le=5000)] = 1500
    parallelism: conint(ge=1, le=1) = 1  # fix 1 by requirement
    extra_instructions: Optional[str] = None


class StructureRequest(BaseModel):
    subject: str
    params: StructureParams = StructureParams()
    mcp: Optional[List[MCPConfig]] = None


class StructureResponse(BaseModel):
    statistics: GenerationStatisticsSchema
    structure: Dict[str, Any]


class SectionsStreamRequest(BaseModel):
    structure: Dict[str, Any]
    params: SectionParams = SectionParams()
    start_index: Optional[int] = 0
    count: Optional[int] = None
    mcp: Optional[List[MCPConfig]] = None


class MCPToolsRequest(BaseModel):
    server_url: str
    auth_token: Optional[str] = None


class ExportRequest(BaseModel):
    content: str
    filename: Optional[str] = "generated_book"
