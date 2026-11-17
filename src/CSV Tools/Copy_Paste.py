import pandas as pd
import argparse as args
import os
from pathlib import Path

class tools:
    def __init__(self,file_name):
        self.file_name = file_name
        self.df = pd.read_csv(file_name)

    def get_cell_data(self,row_index:int,column_index:int):
        self.row_id = row_index
        self.column_id = column_index

        temp = self.df.iloc[self.row_id-1,self.column_id-1]
        return temp

    def get_column_data(self,column_name:str) -> list:
        column_elements = [i for i in self.df.loc[:,column_name]]
        return column_elements

    def get_row_data(self,row_name:int) -> list:
        row_elements = [i for i in self.df.loc[row_name]]
        return row_elements
    
    def show(self):
        return self.df.head()

sheet = tools("benchmarkscientific_products.csv")
specifications = sheet.get_column_data("Specifications")

if __name__ == "__main__":
    parser = args.ArgumentParser(description="Tools for accessing CSV modifactions")
    parser.add_argument("--data",help="Add filepath of .csv file")
    arg = parser.parse_args()

    if not (Path(args.data).is_dir()):
        