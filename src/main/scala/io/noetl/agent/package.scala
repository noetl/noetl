package io.noetl

import java.nio.file.Paths
import _root_.io.noetl.util._

import pureconfig.{
  CamelCase,
  ConfigFieldMapping,
  FieldCoproductHint,
  ProductHint
}

package agent {



  trait NextActionBase

  trait ActionBase {
    val displayName: Option[String]
    val description: Option[String]
    var variables: Option[Map[String, String]]

    def runAction(): Unit = {
      runPrint(this.printMessage)
      runNext
    }

    def runNext(): Unit = ()

    def printMessage = "Empty action"

    def runPrint(msg: String): Unit = {
      println(s"$getCurrentTime $msg")
    }
  }

  trait ActionForkBase extends ActionBase {
    override def printMessage = s"Fork call ${this.displayName} "
  }

  trait ActionJoinBase extends ActionBase {
    override def printMessage = s"Join call ${this.displayName} "
  }

  trait ActionWebserviceBase extends ActionBase {
    val url: String
    val httpMethod: String // request method GET, POST, DELETE
    val contentType: String // request Content-Type
    val httpClientTimeout: Option[String]
    val outputPath: Option[String] // path to the staging folder
    // data received from the previous action
    private var output: Option[String] = None
    private var requestBody: Option[String] = None

    def setRequestBody(data: Option[String]): Unit = this.requestBody = data

    def getRequestBody: Option[String] = this.requestBody
    // canonical form is also JSON object

    def setOutput(data: Option[String]): Unit = this.output = data

    def getOutput: Option[String] = this.output
  }

  // shellTask invokes local shell, which means:
  // a) the engine must execute on Linux/Unix machine;
  // b) commands must be specific only to local host.

  trait ActionShellBase extends ActionBase {
    val shellScript: Option[String] // It might be a script call or just a shell command to be executed on the local machine
    val scriptParams: Option[List[String]] // // each element of scriptParams array shall be supplied to shellScript as a parameter beginning from $1 = [0]
    val outputPath: Option[String] // path to the staging folder
    var output: Option[String] // // shell's stdout will be copied to next actions
  }

  trait ActionJdbcBase extends ActionBase {
    // need to decide how to put passwords into config files
    val databaseUrl: Option[String]
    val queryParams: Option[String]
    val queryString: Option[String] // data received from the previous action
    var output: Option[String]
  }

  trait ActionSshBase extends ActionBase {
    val sshHost: Option[String]
    val sshPort: Option[String] // note string here, not number!
    val sshUser: Option[String]
    // Specify a key pair file as SSH identity_file parameter (ssh -i) - see "man ssh".
    // Using password in sshTask is wrong and must be discouraged.
    val sshIdentityFile: Option[String] // key pair file must reside in local file system
    val shellScript: Option[String] // on the remote host
    val scriptParams: Option[String] // the array of params for remote script
    var output: Option[String]
  }

  trait ActionScpBase extends ActionBase {
    val sourceHost: Option[String]
    val sourcePort: Option[String] // note string here, not number!
    val sourceUser: Option[String]
    // Specify a key pair file as SSH identity_file parameter (ssh -i) - see "man ssh".
    // Using password in sshTask is wrong and must be discouraged.
    val sourceIdentifyFile: Option[String] // key pair file must reside in local file system
    val sourcePath: Option[String] // that file, yeah!
    val targetHost: Option[String] // the array of params for remote script
    // no targetPort, targetUser, targetIdentityFile are necessary for "localhost"
    val targetPath: Option[String]
    val overwriteTarget: String // "always", "newer", "never" are sane options

  }

  trait WorkflowBase {
    val name: String
    val `type`: String
    val displayName: Option[String]
    val description: Option[String]
    var variables: Option[Map[String, String]]
    val input: Option[Map[String, String]]
  }

  sealed trait ActionState

}

package object agent {

  /**
    * https://pureconfig.github.io/docs/overriding-behavior-for-case-classes.html
    *
    * PureConfig provides a way to create a ConfigFieldMapping by defining the naming conventions of the fields in the
    * Scala object and in the configuration file. Some of the most used naming conventions are supported directly in
    * the library:
    *
    * CamelCase (examples: camelCase, useMorePureconfig);
    * SnakeCase (examples: snake_case, use_more_pureconfig);
    * KebabCase: (examples: kebab-case, use-more-pureconfig);
    * PascalCase: (examples: PascalCase, UseMorePureconfig).
    */
  implicit def hint[T] =
    ProductHint[T](ConfigFieldMapping(CamelCase, CamelCase))

  /**
    * https://pureconfig.github.io/docs/overriding-behavior-for-sealed-families.html
    *
    * FieldCoproductHint can also be adapted to write class names in a different ways.
    *
    */
  implicit val actionConfHint = new FieldCoproductHint[ActionConf]("type") {
    override def fieldValue(name: String) =
      name.dropRight("Conf".length).toLowerCase
  }

  def validateWorkflowConfig(configPath: String): WorkflowConf =
    pureconfig.loadConfig[WorkflowConf](Paths.get(configPath)) match {
      case Right(conf) => conf
      case Left(err) =>
        Console.err.println(err.toList)
        throw new Exception(err.head.description)
    }

}
