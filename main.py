import argparse
import sys

from fastapi import FastAPI, Query, Request
from typing import Optional
import requests

from src.routers.users import *
from src.shared.db_connector import database
from src.shared.token_generator import Generate
import src.csv_tools.csv_tools as csv
from src.menu import general_menu

from src.yolo.ModelConverter import Yolo

print(general_menu.general_menu)
try:
    Choice = input("Select a tool from the menu: ")

    if Choice == "1" or Choice.lower() == "yolo":
        while True:
            try:
                model_path = input("[YOLO] Enter model path: ")
                model_name = input("[ONNX] Enter ONNX file name: ")
                Yolo(model_path).ONNX(model_name)
            except KeyboardInterrupt as e:
                print("[CLOSING] Keyboard interrupt detected.")
                break

    elif Choice == "2" or Choice.lower() in ["csv","csv tools","csv tool","csvtools"]:
        csv.main()
except KeyboardInterrupt as e:
    print("\n[KEY INTERRUPY] Exiting the system on KeyboardInterrupt")