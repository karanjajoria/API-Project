from fastapi import FastAPI, Query, Request
from typing import Optional

from src.routers.users import *
from src.shared.db_connector import connect_to_db