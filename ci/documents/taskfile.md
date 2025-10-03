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
