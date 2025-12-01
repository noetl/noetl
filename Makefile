# NoETL Makefile
# 
# This Makefile is a compatibility shim for users familiar with make.
# All functionality has been moved to Taskfile (task command).
# 
# To use the full NoETL automation:
# 1. Run bootstrap to install tools: ./ci/bootstrap/bootstrap.sh
# 2. Use task commands: task --list

.PHONY: help
help:
	@echo "NoETL uses Taskfile for automation."
	@echo ""
	@echo "Quick Start:"
	@echo "  make bootstrap              Run bootstrap to install all tools (task, docker, kubectl, etc.)"
	@echo "  make destroy                Destroy environment and clean up all resources"
	@echo ""
	@echo "After bootstrap, use task commands:"
	@echo "  task --list                 Show all available tasks"
	@echo "  task bootstrap              Complete K8s environment setup"
	@echo "  task build                  Build NoETL Docker image"
	@echo "  task deploy-all             Deploy all components"
	@echo ""
	@echo "For full documentation, see:"
	@echo "  - README.md"
	@echo "  - ci/bootstrap/README.md"

.PHONY: bootstrap
bootstrap:
	@echo "Running NoETL bootstrap..."
	@echo "This will install all required tools (Docker, kubectl, helm, kind, task, pyenv, tfenv, uv, etc.)"
	@./ci/bootstrap/bootstrap.sh
	@echo ""
	@echo "Bootstrap complete! You can now use 'task' commands:"
	@echo "  task --list"

.PHONY: destroy
destroy:
	@echo "Destroying NoETL environment and cleaning up all resources..."
	@task kind:local:cluster-delete || true
	@task docker:local:cleanup-all || true
	@task cache:local:clean || true
	@task noetl:local:clear-all || true
	@echo ""
	@echo "Environment destroyed and caches cleared."

.DEFAULT_GOAL := help
