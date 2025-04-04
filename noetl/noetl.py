# ==================================================================================================================== #
#                                                   NoETL                                                              #
# ==================================================================================================================== #
#                                                                                                                      #
#                   This module contains the main entry point for the NoETL utility.                                   #
#                                                                                                                      #
# ---------------------------------------------------------------------------------------------------------------      #
# Installation Instructions:                                                                                           #
#                                                                                                                      #
# To build and install this library, use the following command from the root of the project:                           #
#                                                                                                                      #
#     pip install .                                                                                                    #
#                                                                                                                      #
# - This installs the library in local Python environment, to execute the `noetl` command directly from the terminal.  #
# - It ensures the CLI and FastAPI components work seamlessly without manual inclusion of project paths.               #
#                                                                                                                      #
# Usage:                                                                                                               #
#                                                                                                                      #
# - Running a specific workflow:                                                                                       #
#     noetl --target call_openai_api --config data/noetl/workflows/target.yaml                                         #
#                                                                                                                      #
# - Running multiple workflows:                                                                                        #
#     noetl --target call_openai_api call_amadeus_api --config data/noetl/workflows/target.yaml                        #
#                                                                                                                      #
# - Running as a REST API server on localhost:                                                                         #
#     noetl --server                                                                                                   #
#                                                                                                                      #
# ==================================================================================================================== #

import argparse
import sys
import os
import yaml
from noetl.job import Job
from noetl.logger import setup_logger
from noetl.route import router
from fastapi import FastAPI, HTTPException
import asyncio

logger = setup_logger(__name__, include_location=True)


def create_server(start_server=False):
    app = FastAPI()
    app.include_router(router, prefix="", tags=["NoETL"])
    if start_server:
        import uvicorn
        uvicorn.run(app, host="localhost", port=8082)
    return app


def cli_args(args=None):
    parser = argparse.ArgumentParser(
        description="Process NoETL workflows.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""Usage:
  noetl --target test_public_api --config data/catalog/payload.yaml
  noetl --target call_openai_api call_amadeus_api --config data/catalog/payload.yaml"""
    )
    parser.add_argument("--load", help="File path or template/config payload.")
    parser.add_argument(
        "--config",
        help="Path to the payload config file (e.g., payload.yaml).",
        default="data/catalog/payload.yaml"
    )
    parser.add_argument(
        "--target", nargs="+", help="Space-separated list to load from the payload config file."
    )
    parser.add_argument("--server", action="store_true", help="Run as REST API service.")
    parsed_args, _ = parser.parse_known_args(args)
    if len(sys.argv) == 1:
        parser.print_help(sys.stdout)
        sys.exit(1)
    return parsed_args


def get_targets(config_path, target_names):
    if not os.path.exists(config_path):
        logger.error(f"Configuration file '{config_path}' does not exist.")
        sys.exit(1)
    try:
        with open(config_path, "r") as file:
            config_data = yaml.safe_load(file)
        missing_targets = [target for target in target_names if target not in config_data]
        if missing_targets:
            logger.error(f"Targets {missing_targets} not found in the configuration file.")
            sys.exit(1)
        return {target: config_data[target] for target in target_names}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML file '{config_path}': {e}")
        sys.exit(1)

def evaluate_args(parsed_args):
    if parsed_args.config and parsed_args.target:
        return get_targets(parsed_args.config, parsed_args.target)
    if parsed_args.load:
        if os.path.exists(parsed_args.load):
            with open(parsed_args.load, "r") as file:
                return yaml.safe_load(file)
        else:
            return yaml.safe_load(parsed_args.load)
    return None

def main():
    parsed_args = cli_args()
    if parsed_args.server:
        create_server(start_server=True)
    else:
        targets_payloads = evaluate_args(parsed_args)
        if not targets_payloads:
            logger.error("Invalid payload.")
            sys.exit(1)
        for target_name, payload in targets_payloads.items():
            logger.info(f"Executing target: {target_name}")
            workflow = Job(payload)
            try:
                asyncio.run(workflow.execute())
                logger.success(f"Target {target_name} completed successfully.")
            except Exception as e:
                logger.critical(f"Processing target {target_name} failed: {str(e)}")
                sys.exit(1)
        logger.info("All targets completed successfully!")

if __name__ == "__main__":
    main()
