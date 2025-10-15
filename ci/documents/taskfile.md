## Installation  

Task offers several installation methods. Installation using package managers is described below. Additional methods are described in the [official documentation](https://taskfile.dev/installation/)

## Homebrew &nbsp;&nbsp;&nbsp;![macos](/ci/documents/img/MacOS.svg "MacOS") ![linux](/ci/documents/img/Linux.svg "Linux")
Task is available via official Homebrew tap [[source](https://github.com/go-task/homebrew-tap/blob/main/Formula/go-task.rb)]:

```shell
brew install go-task/tap/go-task
```

Alternatively it can be installed from the official Homebrew repository [[package](https://formulae.brew.sh/formula/go-task)] [[source](https://github.com/Homebrew/homebrew-core/blob/master/Formula/g/go-task.rb)] by running:

```shell
brew install go-task
```

## Task namespaces (NoETL)

We use intuitive, searchable task aliases with simple namespaces to indicate the scope of each task. Examples:

- kind:cluster-create, kind:cluster-delete, k8s:context-set-kind
- postgres:deploy, postgres:remove, postgres:schema-reset
- noetl:image-build, noetl:deploy, noetl:remove, noetl:redeploy, noetl:reset
- server:debug, server:debug-stop, server:kill-8083
- worker:debug, noetl:worker-debug
- cache:postgres-clear, cache:noetl-clear, cache:logs-clear, cache:clear-all
- dev:stack-up
- docker:images-clear
- ports:kill

All these aliases are additive to the original task names, so existing commands continue to work. Use `task --list` to discover available tasks and aliases.

Typical flows:

```bash
# Build the image and deploy everything into a local Kind cluster
task dev:stack-up

# Redeploy only NoETL components with a fresh image
task noetl:redeploy

# Run server and worker locally for debugging
task server:debug
task worker:debug

# Tear down
task kind:cluster-delete
```

## Setup completions
Some installation methods will automatically install completions too, but if this isn't working for you or your chosen method doesn't include them, you can run `task --completion <shell>` to output a completion script for any supported shell.

Load the completions in your shell's startup config.
This method loads the completion script from the currently installed version of task every time you create a new shell. This ensures that your completions are always up-to-date.

### bash
Add the following line into the `~/.bashrc`
```
eval "$(task --completion bash)"
alias compdef t='task'
```
### zsh
Add the following line into the `~/.zshrc`
```
eval "$(task --completion zsh)"
alias compdef t='task'
```
