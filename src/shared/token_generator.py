# Test file to check and verify token generation using random function
import random
import math
from src.Database.token import used_tokens

def create_token():
    token  = random.randint(100000,999999)
    if token in used_tokens:
        return create_token()
    used_tokens.add(token)
    return token

print(create_token())