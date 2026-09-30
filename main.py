import argparse

from fastapi import FastAPI, Query, Request
from typing import Optional
import requests

from src.routers.users import *
from src.shared.db_connector import database
from src.shared.token_generator import Generate

from src.yolo.ModelConverter import Yolo

Choice = input("""
====================================================================================================
                                            MENU
====================================================================================================
1. Yolo Model Converter                                

""")

if Choice == "1" or Choice.lower() == "yolo":
    while True:
        try:
            model_path = input("[YOLO] Enter model path: ")
            model_name = input("[ONNX] Enter ONNX file name: ")
            Yolo(model_path).ONNX(model_name)
        except KeyboardInterrupt as e:
            print("[CLOSING] Keyboard interrupt detected.")
            break