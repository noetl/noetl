package io.noetl.agent
//import scala.collection.JavaConverters._

case class NextAction(parallelism: Option[String],
                      multithread: Option[String],
                      subscribers: Option[List[String]])

sealed trait ActionConf

case class ForkConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]]
) extends ActionConf

case class JoinConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]]
) extends ActionConf

case class WebserviceConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]],
    url: String,
    httpMethod: String = "GET", // request method GET, POST, DELETE
    contentType: String = "application/json", // request Content-Type
    httpClientTimeout: Option[String],
    outputPath: Option[String] // path to the staging folder
) extends ActionConf {
  // data received from the previous action
  private var requestBody: Option[String] = None
  def setRequestBody(data: Option[String]): Unit = this.requestBody = data
  def getRequestBody: Option[String] = this.requestBody
  // canonical form is also JSON object
  private var output: Option[String] = None
  def setOutput(data: Option[String]): Unit = this.output = data
  def getOutput: Option[String] = this.output
}

// shellTask invokes local shell, which means:
// a) the engine must execute on Linux/Unix machine;
// b) commands must be specific only to local host.

case class ShellConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]],
    shellScript: Option[String], // It might be a script call or just a shell command to be executed on the local machine
    scriptParams: Option[List[String]], // // each element of scriptParams array shall be supplied to shellScript as a parameter beginning from $1 = [0]
    outputPath: Option[String], // path to the staging folder
    var output: Option[String] = None // // shell's stdout will be copied to next actions
) extends ActionConf

case class JdbcConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]],
    // need to decide how to put passwords into config files
    databaseUrl: Option[String],
    queryParams: Option[String],
    queryString: Option[String], // data received from the previous action
    var output: Option[String] = None
) extends ActionConf

case class SshConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]],
    sshHost: Option[String],
    sshPort: Option[String], // note string here, not number!
    sshUser: Option[String],
    // Specify a key pair file as SSH identity_file parameter (ssh -i) - see "man ssh".
    // Using password in sshTask is wrong and must be discouraged.
    sshIdentityFile: Option[String], // key pair file must reside in local file system
    shellScript: Option[String], // on the remote host
    scriptParams: Option[String], // the array of params for remote script
    var output: Option[String] = None
) extends ActionConf

case class ScpConf(
    displayName: Option[String],
    description: Option[String],
    next: Option[NextAction],
    var variables: Option[Map[String, String]],
    sourceHost: Option[String],
    sourcePort: Option[String], // note string here, not number!
    sourceUser: Option[String],
    // Specify a key pair file as SSH identity_file parameter (ssh -i) - see "man ssh".
    // Using password in sshTask is wrong and must be discouraged.
    sourceIdentifyFile: Option[String], // key pair file must reside in local file system
    sourcePath: Option[String], // that file, yeah!
    targetHost: Option[String], // the array of params for remote script
    // no targetPort, targetUser, targetIdentityFile are necessary for "localhost"
    targetPath: Option[String],
    overwriteTarget: String = "always" // "always", "newer", "never" are sane options
) extends ActionConf

case class WorkflowConf(
    name: String,
    `type`: String,
    displayName: Option[String],
    description: Option[String],
    start: Option[NextAction],
    var variables: Option[Map[String, String]],
    input: Option[Map[String, String]],
    actions: Map[String, ActionConf]
)
