import os
from typing import Optional,Any
from loguru import logger
import re
from noetl.api.storage import read_yaml


class Config(dict):
    def __init__(self, *args, **kwargs):
        super(Config, self).__init__(*args, **kwargs)
        self.log_level: str = os.getenv('LOG_LEVEL', 'info')
        self.config_path: Optional[str] = None

    def get_keys(self) -> list:
        return list(self.keys())

    def get_value(self, path: str = None):
        try:
            value = self
            if path is None:
                return value
            keys = path.split(".")
            for key in keys:
                value = value.get(key)
                if value is None:
                    return None
            return value
        except Exception as e:
            logger.error(e)

    def set_config_path(self, config_path: Optional[str] = None):
        """
        Sets the configuration path.
        :param config_path: path to the configuration file.
        :type config_path: Optional[str]
        """
        if config_path:
            self.config_path = config_path
        else:
            logger.error("Config path is empty")
    @classmethod
    async def create(cls, config_path):
        data = await read_yaml(config_path)
        return cls(data)


class ConfigTemplateEvaluator:
    def __init__(self, template_object: dict):
        self.template_object = template_object

    def get_match(self, match):
        key = match.group(1)
        return get_object_value(self.template_object, key)

    def evaluate(self, input_string):
        return re.sub(r"{{\s*(.*?)\s*}}", self.get_match, input_string)


def get_matches(input_string: str):
    """
    Returns a list of matches found in the input string based on the pattern.
    :param input_string: The string to search for matches.
    :type input_string: str
    :return: A list of matches.
    :rtype: list
    """
    pattern = r"{{\s*(.*?)\s*}}"
    matches = re.findall(pattern, input_string)
    return matches


def get_object_value(input_object: dict, path: str):
    """
    Retrieves the value from the input_object dictionary based on the provided path.
    :param input_object: The input dictionary.
    :type input_object: dict
    :param path: The path to the desired value.
    :type path: str
    :return: The value from the input_object dictionary based on the provided path.
    :rtype: Any
    """
    keys = path.split(".")
    value = input_object
    for key in keys:
        value = value.get(key)
        if value is None:
            return None
    return value


def evaluate_template_input(template_object, input_string):
    """
    Evaluates and replaces the placeholders in the input_string with the corresponding values from the template_object.
    :param template_object: The input dictionary.
    :type template_object: dict
    :param input_string: The string containing placeholders.
    :type input_string: str
    :return: The input string with placeholders replaced with corresponding values from the template_object.
    :rtype: str
    """
    evaluator = ConfigTemplateEvaluator(template_object)
    return evaluator.evaluate(input_string)


def set_object_value(template_object: dict, path: str, value: Any):
    """
    Sets the value in the template_object dictionary based on the provided path.
    :param template_object: The input dictionary.
    :type template_object: dict
    :param path: The path to the desired value.
    :type path: str
    :param value: The value to set.
    :type value: Any
    """
    keys = path.split('.')
    current_path = template_object
    for key in keys[:-1]:
        if key not in current_path:
            current_path[key] = {}
        current_path = current_path[key]
    current_path[keys[-1]] = value
