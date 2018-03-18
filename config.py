import yaml

class Config:
    """
    Configuration parsed directly from a YAML file
    """
    def __init__(self):
        self.config = None

    def load(self, config_file: str):
        with open(config_file, 'r') as stream:
            self.config = yaml.load(stream)

    def get(self, field: str):
        return self.config[field]

