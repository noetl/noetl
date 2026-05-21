npm install -D @playwright/test
npx playwright install


```sh
# API-only local kind validation skips UI specs by default.
npx playwright test

# UI validation requires the gateway/UI service.
NOETL_RUN_UI_E2E=1 NOETL_UI_BASE_URL=http://localhost:30080 npx playwright test

npx playwright test --ui  # Open mini app 
npx playwright test --debug  # Run rebug mode, step by step run
npx playwright test tests/newpatient.spec.ts --debug  # Run certain test
```

uv venv
source .venv/bin/activate   
pip install -e .      
noetl --host localhost --port 8082 register playbook --file ../e2e/fixtures/playbooks/hello_world/hello_world.yaml

git checkout main
git pull
git checkout e2e
git merge main
git push
noetl k8s reset

cd tests/playwright
npx playwright test --ui
