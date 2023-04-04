import yaml
import signal
from loguru import logger
import concurrent.futures

with open('filename.yaml') as f:
    my_dict = yaml.safe_load(f)
