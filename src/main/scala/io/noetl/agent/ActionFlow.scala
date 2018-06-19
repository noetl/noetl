package io.noetl.agent

import scala.util.{Try,Success,Failure}

case class NextAction(parallelism: Option[String] = None,
                      multithread: Option[String] = None,
                      subscribers: Option[List[Action]] = None)
    extends NextActionBase

object NextAction {
  def apply(nextActionConf: Option[NextActionConf],
            actions: Map[String, ActionConf]): NextAction = (nextActionConf,actions) match {
    case (nextActionConf: Option[NextActionConf],actions: Map[String, ActionConf]) => Try(new NextAction(
      parallelism = nextActionConf.get.parallelism,
      multithread = nextActionConf.get.multithread,
      subscribers = Some(nextActionConf.get.subscribers.get.map(actionKey => {
        // println(s"actionKey: $actionKey")
        val actionConf = actions(actionKey)
        conf2action(actionConf, actions)
      }))
    )).getOrElse(new NextAction())
    case (_,_) => new NextAction()
  }
}

trait Action extends ActionBase {
  val next: Option[NextAction]
  override def runNext(): Unit = Try(this.next.get.subscribers.get.foreach(x => x.runAction)) match {
    case Success(_) =>
    case Failure(ex) =>
  }
}

case class ActionFork(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
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
      next = Some(NextAction(forkConf.next, actions)).orElse(None),
      variables = forkConf.variables
    )
  }
}

case class ActionJoin(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
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
      next = Some(NextAction(joinConf.next, actions)).orElse(None),
      variables = joinConf.variables
    )
  }
}

case class ActionWebservice(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
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
      next = Some(NextAction(actionConf.next, actions)).orElse(None),
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
    next: Option[NextAction],
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
      next = Some(NextAction(actionConf.next, actions)).orElse(None),
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
    next: Option[NextAction],
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
      next = Some(NextAction(actionConf.next, actions)).orElse(None),
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
    next: Option[NextAction],
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
      next = Some(NextAction(actionConf.next, actions)).orElse(None),
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
    next: Option[NextAction],
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
      next = Some(NextAction(actionConf.next, actions)).orElse(None),
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

case class ActionFlow(
    name: String,
    `type`: String,
    displayName: Option[String],
    description: Option[String],
    start: Option[NextAction],
    var variables: Option[Map[String, String]],
    input: Option[Map[String, String]],
    actions: Map[String, Action]
) extends WorkflowBase

object ActionFlow {
  def apply(workflow: WorkflowConf): ActionFlow = {
    new ActionFlow(
      name = workflow.name,
      `type` = workflow.`type`,
      displayName = workflow.displayName,
      description = workflow.description,
      start = Some(NextAction(workflow.start, workflow.actions)),
      variables = workflow.variables,
      input = workflow.input,
      actions = workflow.actions map {
        case (key, value) => (key, conf2action(value, workflow.actions))
      }
    )
  }
}
