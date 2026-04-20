from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class MappingStatus(str, Enum):

    GREEN = "unambiguous"
    YELLOW_GREEN = "high_similarity"
    YELLOW = "near_tier"
    RED = "low_similarity"
    BLACK = "no_correspondence"

class MappingCandidate(BaseModel):

    model_id: str = Field(..., description="The AGORA model ID (filename without extension, e.g., 'Escherichia_coli_K12')")

    score: float = Field(..., description="The raw match score assigned by the algorithm (usually 0-100)")

    reason: Optional[str] = Field(None, description="The rationale for this specific match (e.g., 'exact synonym match')")

class MappingItem(BaseModel):

    query_name: str = Field(..., description="The bacterium name provided in the user input")

    abundance: Optional[float] = Field(None, description="Relative abundance provided in input")

    mapped_id: Optional[str] = Field(None, description="The ID of the preferred/best AGORA model match")

    status: MappingStatus = Field(..., description="The overall confidence level (traffic light status)")

    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Normalized confidence score between 0.0 and 1.0")

    candidates: List[MappingCandidate] = Field(default_factory=list, description="List of all potential AGORA candidates sorted by relevance")

    class Config:
        use_enum_values = True

class MappingReport(BaseModel):

    job_id: str = Field(..., serialization_alias="jobId", description="Job ID in the PostgreSQL database")

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Report generation date (ISO 8601)")

    total_bacteria: int = Field(..., serialization_alias="total_bacteria")

    results: List[MappingItem] = Field(default_factory=list, description="List of results for each bacterium")

    def to_json(self) -> str:
        """Helper method to generate the final JSON using the correct aliases"""
        return self.model_dump_json(by_alias=True, indent=2)