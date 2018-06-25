package io.noetl.agent

import scala.util.{Try,Success,Failure}
//import scala.collection.mutable.{Seq => mSeq}

case class NextAction(parallelism: Int = 1,
                      multithread: Int = 1,
                      subscribers: List[String] = List.empty)
    extends NextActionBase {

  def isDefined: Boolean = this.subscribers.nonEmpty

}

object NextAction {
  def apply(nextActionConf: Option[NextActionConf],
            actions: Map[String, ActionConf]): NextAction = (nextActionConf,actions) match {
    case (Some(nextActionConf),actions: Map[String, ActionConf]) => Try(
      new NextAction(
      parallelism = Try(nextActionConf.parallelism.get.toInt).getOrElse(1),
      multithread = Try(nextActionConf.multithread.get.toInt).getOrElse(1),
      subscribers = Try(nextActionConf.subscribers.get).getOrElse(List.empty)
     )
    ).getOrElse(new NextAction)
    case (_,_) => new NextAction
  }
}

// case class Dependency (actionName: String, state: ActionState)

trait Action extends ActionBase {

    // this is link to actions that this action may fork.
    val next: NextAction

    // state is changed each time we call runAction. "Pending" is default. We may change the default name later.
    var state: ActionState = Pending

    // populated by addDependency method
    var dependency: Vector[Action] = Vector.empty
    // var dependency: Vector[Dependency] = Vector.empty

    /**
      * addDependency is called any time we need to link this action with ancestor.
      */
    def addDependency(action: Action): Unit = this.dependency = this.dependency ++ Vector(action)

    /**
     * Pending assigns a "PENDING" flag to the action state.
     */
    def pending() = this.state = Pending

    /**
      * Processing method is called before actual execution of the given action is called.
      */
    def processing() = this.state = Processing

    /**
      * Finished flags that this action is done successfully.
      */
    def finished() = this.state = Finished

    /**
      * Failed  method should be assign when action run is failed by any reason.
      */
    def failed() = this.state = Failed

    /**
      * isPending checks the state of this action.
      */
    def isPending() = if (this.state == Pending) true else false

    /**
      * runAction method executes any command defined by actual action.
      */
    def runAction(): Unit = {
        // filter actions from dependency list

        val dependencyCheck = this.dependency.filter(x => x.state != Finished)
        if (dependencyCheck.isEmpty) {
            this.processing()
            Try(runPrint(this.printMessage)) match {
                case Success(_) => this.finished()
                case Failure(ex) => {
                    this.failed()
                    println(s"runAction failed ${ex}")
                }
            }
        }
    }
}

case class ActionFork(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]]
) extends Action
    with ActionForkBase {
  override def printMessage = s"Fork call ${this.displayName} "
}

object ActionFork {
  def apply(forkConf: ForkConf,
            actions: Map[String, ActionConf]): ActionFork = {
    new ActionFork(
      displayName = forkConf.displayName,
      description = forkConf.description,
      next = NextAction(forkConf.next, actions),
      variables = forkConf.variables
    )
  }
}

case class ActionJoin(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]]
) extends Action
    with ActionJoinBase {
  override def printMessage = s"Join call ${this.displayName} "
}

object ActionJoin {
  def apply(joinConf: JoinConf,
            actions: Map[String, ActionConf]): ActionJoin = {
    new ActionJoin(
      displayName = joinConf.displayName,
      description = joinConf.description,
      next = NextAction(joinConf.next, actions),
      variables = joinConf.variables
    )
  }
}

case class ActionWebservice(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]],
    url: String,
    httpMethod: String = "GET",
    contentType: String = "application/json",
    httpClientTimeout: Option[String],
    outputPath: Option[String]
) extends Action
    with ActionWebserviceBase {
  override def printMessage =
    s"Webservice call ${this.displayName} - curl ${this.httpMethod} ${this.url}"
}

object ActionWebservice {
  def apply(actionConf: WebserviceConf,
            actions: Map[String, ActionConf]): ActionWebservice = {
    new ActionWebservice(
      displayName = actionConf.displayName,
      description = actionConf.description,
      next = NextAction(actionConf.next, actions),
      variables = actionConf.variables,
      url = actionConf.url,
      httpMethod = actionConf.httpMethod,
      contentType = actionConf.contentType,
      httpClientTimeout = actionConf.httpClientTimeout,
      outputPath = actionConf.outputPath
    )
  }
}

case class ActionShell(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]],
    shellScript: Option[String],
    scriptParams: Option[List[String]],
    outputPath: Option[String],
    var output: Option[String] = None
) extends Action
    with ActionShellBase {
  override def printMessage =
    s"Shell call  for ${this.displayName} - sh ${this.shellScript} ${this.scriptParams}"
}

object ActionShell {
  def apply(actionConf: ShellConf,
            actions: Map[String, ActionConf]): ActionShell = {
    new ActionShell(
      displayName = actionConf.displayName,
      description = actionConf.description,
      next = NextAction(actionConf.next, actions),
      variables = actionConf.variables,
      shellScript = actionConf.shellScript,
      scriptParams = actionConf.scriptParams,
      outputPath = actionConf.outputPath,
      output = actionConf.output
    )
  }
}

case class ActionJdbc(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]],
    databaseUrl: Option[String],
    queryParams: Option[String],
    queryString: Option[String],
    var output: Option[String] = None
) extends Action
    with ActionJdbcBase {
  override def printMessage =
    s"Jdbc call for ${this.displayName} - jdbc ${this.databaseUrl} ${this.queryParams} ${this.queryString}"
}

object ActionJdbc {
  def apply(actionConf: JdbcConf,
            actions: Map[String, ActionConf]): ActionJdbc = {
    new ActionJdbc(
      displayName = actionConf.displayName,
      description = actionConf.description,
      next = NextAction(actionConf.next, actions),
      variables = actionConf.variables,
      databaseUrl = actionConf.databaseUrl,
      queryParams = actionConf.queryParams,
      queryString = actionConf.queryString,
      output = actionConf.output
    )
  }
}

case class ActionSsh(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]],
    sshHost: Option[String],
    sshPort: Option[String],
    sshUser: Option[String],
    sshIdentityFile: Option[String],
    shellScript: Option[String],
    scriptParams: Option[String],
    var output: Option[String] = None
) extends Action
    with ActionSshBase {
  override def printMessage =
    s"Ssh call for ${this.displayName} ssh ${this.sshHost} ${this.sshPort} ${this.sshUser}"
}

object ActionSsh {
  def apply(actionConf: SshConf,
            actions: Map[String, ActionConf]): ActionSsh = {
    new ActionSsh(
      displayName = actionConf.displayName,
      description = actionConf.description,
      next = NextAction(actionConf.next, actions),
      variables = actionConf.variables,
      sshHost = actionConf.sshHost,
      sshPort = actionConf.sshPort,
      sshUser = actionConf.sshUser,
      sshIdentityFile = actionConf.sshIdentityFile,
      shellScript = actionConf.shellScript,
      scriptParams = actionConf.scriptParams,
      output = actionConf.output
    )
  }
}

case class ActionScp(
    displayName: Option[String],
    description: Option[String],
    next: NextAction,
    var variables: Option[Map[String, String]],
    sourceHost: Option[String],
    sourcePort: Option[String],
    sourceUser: Option[String],
    sourceIdentifyFile: Option[String],
    sourcePath: Option[String],
    targetHost: Option[String],
    targetPath: Option[String],
    overwriteTarget: String = "always"
) extends Action
    with ActionScpBase {
  override def printMessage =
    s"Scp call for ${this.displayName} ssh ${this.sourceHost} ${this.sourcePort} ${this.sourceUser}"
}

object ActionScp {
  def apply(actionConf: ScpConf,
            actions: Map[String, ActionConf]): ActionScp = {
    new ActionScp(
      displayName = actionConf.displayName,
      description = actionConf.description,
      next = NextAction(actionConf.next, actions),
      variables = actionConf.variables,
      sourceHost = actionConf.sourceHost,
      sourcePort = actionConf.sourcePort,
      sourceUser = actionConf.sourceUser,
      sourceIdentifyFile = actionConf.sourceIdentifyFile,
      sourcePath = actionConf.sourcePath,
      targetHost = actionConf.targetHost,
      targetPath = actionConf.targetPath,
      overwriteTarget = actionConf.overwriteTarget
    )
  }
}

case class Dependency (action: String, actions: List[String])

case class ActionFlow(
    name: String,
    `type`: String,
    displayName: Option[String],
    description: Option[String],
    start: NextAction,
    var variables: Option[Map[String, String]],
    input: Option[Map[String, String]],
    actions: Map[String,Action]
) extends WorkflowBase {
    def getAction(actionName: String) = this.actions(actionName)
    def actionExists(actionName: String): Boolean = Try(getAction(actionName: String)) match {
        case Success(_) => true
        case Failure(ex) => false
    }

    def buildActionDependency() = {
        this.actions foreach  {case (name, action) => {
            val nextActions = action.next.subscribers
            nextActions.foreach(actionName => {
                if (actionExists(actionName))   {
                    this.getAction(actionName).addDependency( this.getAction(name))
                }
            })
        }
        }
    }

    def runFlow() = ActionFlow.runFlow(this)

}

object ActionFlow {
  def apply(implicit workflow: WorkflowConf): ActionFlow = {
      implicit val actionFlow = new ActionFlow(
      name = workflow.name,
      `type` = workflow.`type`,
      displayName = workflow.displayName,
      description = workflow.description,
      start = NextAction(workflow.start, workflow.actions),
      variables = workflow.variables,
      input = workflow.input,
      actions = workflow.actions map {
        case (key, value) => (key, conf2action(value, workflow.actions))
       }
    )
      // both way, either buildActionDependency from case class or from this companion object, would build an action dependencies.
      //actionFlow.buildActionDependency
      this.buildActionDependency
      actionFlow
  }

    def buildActionDependency(implicit actionFlow: ActionFlow) = {
        actionFlow.actions foreach  {case (name, action) => {
            val nextActions = action.next.subscribers
            nextActions.foreach(actionName => {
                if (actionFlow.actionExists(actionName))   {
                    actionFlow.getAction(actionName).addDependency( actionFlow.getAction(name))
                }
            })
        }
        }
    }

    def getNextActions(nextAction: NextAction)(implicit actionFlow: ActionFlow): Option[List[Action]] = {
        if (nextAction.subscribers.isEmpty)
            None
        else
            // in the filter we validate action name in the actions registry Map
            Some(nextAction.subscribers.filter(actionName => actionFlow.actionExists(actionName)).map(actionName => actionFlow.getAction(actionName)))
    }

    def runNextAction(action: Action)(implicit actionFlow: ActionFlow): Unit = {
        getNextActions(action.next) match {
            case Some(nextAction) => nextAction.foreach(actionEntry => {
                actionEntry.runAction()
                runNextAction(actionEntry)
            })
            case None =>
        }
    }

    def runFlow(implicit actionFlow: ActionFlow) = {

        getNextActions(actionFlow.start) match {
            case Some(actionList) => {
                actionList.foreach(action => {
                    action.runAction()
                    runNextAction(action)
                })
            }
            case None => throw new Exception("Workflow starting point is not defined")
        }
    }



  def conf2action(actionConf: ActionBase,
                  actions: Map[String, ActionConf]): Action = actionConf match {
    case forkConf: ForkConf => ActionFork(forkConf, actions)
    case joinConf: JoinConf => ActionJoin(joinConf, actions)
    case webserviceConf: WebserviceConf =>
      ActionWebservice(webserviceConf, actions)
    case shellConf: ShellConf => ActionShell(shellConf, actions)
    case jdbcConf: JdbcConf   => ActionJdbc(jdbcConf, actions)
    case sshConf: SshConf     => ActionSsh(sshConf, actions)
    case scpConf: ScpConf     => ActionScp(scpConf, actions)
  }
} // end ActionFlow
