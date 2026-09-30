from ultralytics import YOLO

class Yolo():
    def __init__(self,model_path):
        # Load model as an .pt formate (Ultralytics YOLO formate)
        self.model = YOLO(model_path)

    def ONNX(self):
        # Convert yolo formate model to ONNX formate
        ONNX_temp = self.model.export(formate= "onnx")
        print(f"[STATUS] Export completed successfully:\t{ONNX_temp}")