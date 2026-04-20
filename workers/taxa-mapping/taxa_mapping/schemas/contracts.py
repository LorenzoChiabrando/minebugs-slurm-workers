from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class JobMessage:
    job_id: int
    file_path: str

@dataclass(frozen=True)
class JobResult:
    job_id: int
    output_path: str
    total_bacteria: int
    error: Optional[str] = None
