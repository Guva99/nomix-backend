from pydantic import BaseModel


class PhotoPayload(BaseModel):
    file_url: str
    user_id: int