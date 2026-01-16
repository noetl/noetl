import importlib.util
import sys

gateway_url = (gateway_url or '').strip()
username = (username or '').strip()
password = (password or '').strip()
two_fa_code = (two_fa_code or '').strip()

manual_flag = str(manual).lower() in {'true', '1', 'yes'}
paper_flag = str(paper).lower() in {'true', '1', 'yes'}
headless_flag = str(headless).lower() in {'true', '1', 'yes'}

script_path = "/opt/noetl/scripts/ibkr/authenticate_gateway.py"
spec = importlib.util.spec_from_file_location("authenticate_gateway", script_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load helper script: {script_path}")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

argv = ["--gateway-url", gateway_url, "--timeout-seconds", str(timeout_seconds)]
if username:
    argv.extend(["--username", username])
if password:
    argv.extend(["--password", password])
if two_fa_code:
    argv.extend(["--two-fa-code", two_fa_code])
if paper_flag:
    argv.append("--paper")
if manual_flag:
    argv.append("--manual")
if headless_flag:
    argv.append("--headless")

exit_code = module.main(argv)
result = {"status": "ok" if exit_code == 0 else "error", "exit_code": exit_code}
if exit_code != 0:
    raise RuntimeError(f"IBKR login helper failed with exit code {exit_code}")
