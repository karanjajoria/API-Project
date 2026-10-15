import random
from src.encoder.randomizer import codes

class Encoder:
    def __init__(self,codes):
        self.code = random.choice(codes)

    def run_pipeline(self):
        