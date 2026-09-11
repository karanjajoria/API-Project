from fastapi import FastAPI, Query, Request
from typing import Optional
import requests

from src.routers.users import *
from src.shared.db_connector import database
from src.shared.token_generator import create_token

print(create_token())

