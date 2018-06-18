package io.noetl.agent


case class NextAction (  parallelism: Option[String],
                         multithread: Option[String],
                         subscribers: Option[List[Action]]) extends NextActionBase {
}

sealed trait Action extends ActionBase {
  val next: Option[NextAction]
}

case class ActionFork(
                     displayName: Option[String],
                     description: Option[String],
                     next: Option[NextAction],
                     var variables: Option[Map[String, String]]
                   ) extends Action with ActionForkBase {
  override def printMessage = s"Fork call ${this.displayName} "
}

case class ActionJoin(
                     displayName: Option[String],
                     description: Option[String],
                     next: Option[NextAction],
                     var variables: Option[Map[String, String]]
                   ) extends Action with ActionJoinBase {
  override def printMessage = s"Join call ${this.displayName} "
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
                         ) extends Action with ActionWebserviceBase {
  override def printMessage = s"Webservice call ${this.displayName} - curl ${this.httpMethod} ${this.url}"
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
                    ) extends Action with ActionShellBase {
  override def printMessage = s"Shell call  for ${this.displayName} - sh ${this.shellScript} ${this.scriptParams}"
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
                   ) extends Action with ActionJdbcBase {
  override def printMessage = s"Jdbc call for ${this.displayName} - jdbc ${this.databaseUrl} ${this.queryParams} ${this.queryString}"
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
                  ) extends Action with ActionSshBase {
  override def printMessage = s"Ssh call for ${this.displayName} ssh ${this.sshHost} ${this.sshPort} ${this.sshUser}"
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
                  ) extends Action with ActionScpBase {
  override def printMessage = s"Scp call for ${this.displayName} ssh ${this.sourceHost} ${this.sourcePort} ${this.sourceUser}"
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
