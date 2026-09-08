from pydantic import BaseModel
from src.shared.helper import email_verifier

class User(BaseModel):
    # Fields which are neccessary
    username: str
    password: str

    first_name: str 
    last_name: str | None=None
    profile_pic:str | None=None
    email_id: str 
    mobile_number: int
    backup_mail: str | None=None
    recovery_code:str | None=None

