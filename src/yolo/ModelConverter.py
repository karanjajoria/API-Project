from ultralytics import YOLO

class Yolo():
    def __init__(self,model_path):
        # Load model as an .pt formate (Ultralytics YOLO formate)
        self.model = YOLO(model_path)

    def ONNX(self,ModelName):
        # Convert yolo formate model to ONNX formate
        ONNX_temp = self.model.export(format= "onnx", name = f"models/ONNX/{ModelName}")
        print(f"[STATUS] Export completed successfully:\t{ONNX_temp}")