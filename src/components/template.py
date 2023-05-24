import asyncio
import re
import json
from src.storage import read_yaml
from typing import Any


class TemplateEvaluator:
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
    evaluator = TemplateEvaluator(template_object)
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


if __name__ == "__main__":
    async def fast_test():
        config_path = "../conf/workflow_1.yaml"
        raw_config = await read_yaml(config_path)
        # Replace template's placeholders in the raw_config
        processed_config = json.loads(evaluate_template_input(raw_config, json.dumps(raw_config)))
        print(processed_config)


    asyncio.run(fast_test())
