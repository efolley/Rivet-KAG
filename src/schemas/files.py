from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    filename: str
    doc_type: str
    chunks_upserted: int
