package io.noetl.agent
//import scala.collection.JavaConverters._

case class NextActionConf(parallelism: Option[String],
                      multithread: Option[String],
                      subscribers: Option[List[String]]) extends NextActionBase

sealed trait ActionConf extends ActionBase {
  val next: Option[NextActionConf]
}

case class ForkConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]]
) extends ActionConf with ActionForkBase {
  override def printMessage = s"ForkConf call ${this.displayName} "
}

case class JoinConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]]
) extends ActionConf with ActionJoinBase {
  override def printMessage = s"JoinConf call ${this.displayName} "
}

case class WebserviceConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    url: String,
    httpMethod: String = "GET",
    contentType: String = "application/json",
    httpClientTimeout: Option[String],
    outputPath: Option[String]
) extends ActionConf {
  override def printMessage = s"WebserviceConf call ${this.displayName} - curl ${this.httpMethod} ${this.url}"
}


case class ShellConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    shellScript: Option[String],
    scriptParams: Option[List[String]],
    outputPath: Option[String],
    var output: Option[String] = None
) extends ActionConf with ActionShellBase {
  override def printMessage = s"ShellConf call for ${this.displayName} - sh ${this.shellScript} ${this.scriptParams}"
}

case class JdbcConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    databaseUrl: Option[String],
    queryParams: Option[String],
    queryString: Option[String],
    var output: Option[String] = None
) extends ActionConf with ActionJdbcBase {
  override def printMessage = s"JdbcConf call for ${this.displayName} - jdbc ${this.databaseUrl} ${this.queryParams} ${this.queryString}"
}

case class SshConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    sshHost: Option[String],
    sshPort: Option[String],
    sshUser: Option[String],
    sshIdentityFile: Option[String],
    shellScript: Option[String],
    scriptParams: Option[String],
    var output: Option[String] = None
) extends ActionConf with ActionSshBase {
  override def printMessage = s"SshConf call for ${this.displayName} ssh ${this.sshHost} ${this.sshPort} ${this.sshUser}"
}

case class ScpConf (
    displayName: Option[String],
    description: Option[String],
    next: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    sourceHost: Option[String],
    sourcePort: Option[String],
    sourceUser: Option[String],
    sourceIdentifyFile: Option[String],
    sourcePath: Option[String],
    targetHost: Option[String],
    targetPath: Option[String],
    overwriteTarget: String = "always"
) extends ActionConf with ActionScpBase {
  override def printMessage = s"ScpConf call for ${this.displayName} ssh ${this.sourceHost} ${this.sourcePort} ${this.sourceUser}"
}

case class WorkflowConf(
    name: String,
    `type`: String,
    displayName: Option[String],
    description: Option[String],
    start: Option[NextActionConf],
    var variables: Option[Map[String, String]],
    input: Option[Map[String, String]],
    actions: Map[String, ActionConf]
)
