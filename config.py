import yaml
import os.path

# https://stackoverflow.com/questions/528281/how-can-i-include-a-yaml-file-inside-another
class Loader(yaml.SafeLoader):
    def __init__(self, stream):
        self._root = os.path.split(stream.name)[0]
        super(Loader, self).__init__(stream)

    def include(self, node):
        filename = os.path.join(self._root, self.construct_scalar(node))
        with open(filename, 'r') as f:
            return yaml.load(f, Loader)

Loader.add_constructor('!include', Loader.include)

class Config:
    """
    Configuration parsed directly from a YAML file
    """
    def __init__(self):
        self.config = None

    def load(self, config_file: str):
        with open(config_file, 'r') as stream:
            self.config = yaml.load(stream, Loader)

    def load_str(self, config_str: str):
        self.config = yaml.load(config_str)

    def get(self, field: str):
        return self.config[field]
